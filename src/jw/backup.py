"""JW-04: independent deletion journal, backups with retention, purge on rotation and restore
(FR-ADM-03, FR-PRF-09 step 4, NFR-PRV-03).

The journal is an append-only file beside the database, not inside it, so restoring an older
database cannot resurrect a deleted source: restore and every rotation re-apply the journal with
the same erasure the live workspace uses. The journal holds IDs and hashes only, never content.
"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .contracts import require, utcnow
from .store import SCHEMA_VERSION

JOURNAL = "deletion-journal.jsonl"
DAILY, WEEKLY = 7, 4


def journal(root):
    path = Path(root) / JOURNAL
    if not path.is_file():
        return {}
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            entries[entry["sha256"]] = entry
    return entries


def sync_journal(ws):
    """Append every deletion the database knows and the journal does not. Idempotent."""
    known = journal(ws.store.root)
    rows = ws.db.execute("SELECT d.source_id, s.sha256, d.deleted_at FROM deletions d "
                         "JOIN sources s ON s.id=d.source_id ORDER BY d.deleted_at").fetchall()
    missing = [r for r in rows if r["sha256"] not in known]
    if missing:
        with (ws.store.root / JOURNAL).open("a", encoding="utf-8") as stream:
            for row in missing:
                stream.write(json.dumps({"source_id": row["source_id"], "sha256": row["sha256"],
                                         "deleted_at": row["deleted_at"]}, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return len(missing)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _apply(ws, entries, suppressions=()):
    """Erase every still-active source the journal says was deleted, and re-insert every journaled
    suppression. Returns the erased source IDs."""
    from .suppression import apply_journal

    apply_journal(ws, suppressions)
    purged = []
    for row in ws.db.execute("SELECT id, sha256 FROM sources WHERE state='active'").fetchall():
        if row["sha256"] in entries:
            ws.delete_source(row["id"])
            purged.append(row["id"])
    return purged


def _open_copy(source, scratch):
    from .workspace import Workspace

    root = Path(scratch) / "ws"
    root.mkdir()
    shutil.copyfile(source, root / "workspace.sqlite3")
    return Workspace(root)


def _close_flat(ws):
    # Fold the WAL into the main file so a single file can be moved.
    ws.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    ws.db.execute("PRAGMA journal_mode=DELETE")
    path = ws.store.root / "workspace.sqlite3"
    ws.close()
    return path


def _write_manifest(path, schema, created_at, purged_through, suppressions=0):
    manifest = {"schema_version": schema, "sha256": _sha(path), "created_at": created_at,
                "journal_entries": purged_through, "suppression_entries": suppressions, "contains": ["database"], "secrets": "none"}
    Path(str(path) + ".json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return manifest


def _manifest(path):
    meta = Path(str(path) + ".json")
    require(Path(path).is_file() and meta.is_file(), "backup_invalid", "Backup or its manifest is missing.")
    manifest = json.loads(meta.read_text(encoding="utf-8"))
    require(manifest.get("sha256") == _sha(path), "backup_invalid", "Backup does not match its manifest hash.")
    require(isinstance(manifest.get("schema_version"), int) and manifest["schema_version"] <= SCHEMA_VERSION,
            "unsupported_schema", "Backup schema is newer than this application.")
    return manifest


def backup(ws, to=None):
    """Snapshot the database, then rotate: keep 7 daily and 4 weekly, purge the kept ones."""
    sync_journal(ws)
    dest = Path(to) if to else ws.store.root / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    created = utcnow()
    path = dest / ("backup-" + datetime.fromisoformat(created).strftime("%Y%m%dT%H%M%S%f") + ".sqlite3")
    target = sqlite3.connect(path)
    try:
        ws.db.backup(target)
    finally:
        target.close()
    from .suppression import journal as suppression_journal

    _write_manifest(path, SCHEMA_VERSION, created, len(journal(ws.store.root)),
                    len(suppression_journal(ws.store.root)))
    ws.store.audit("backup_created", path.name)
    from .suppression import journal as suppression_journal

    rotated = rotate(dest, journal(ws.store.root), suppression_journal(ws.store.root))
    return {"backup": str(path), "kept": rotated["kept"], "removed": rotated["removed"],
            "purged": rotated["purged"]}


def _stamp(path):
    return datetime.strptime(path.name[len("backup-"):-len(".sqlite3")], "%Y%m%dT%H%M%S%f")


def rotate(dest, entries, suppressions=()):
    backups = sorted(Path(dest).glob("backup-*.sqlite3"), key=_stamp, reverse=True)
    keep, days, weeks = set(), [], []
    for path in backups:
        stamp = _stamp(path)
        if stamp.date() not in days and len(days) < DAILY:
            days.append(stamp.date())
            keep.add(path)
        week = stamp.isocalendar()[:2]
        if week not in weeks and len(weeks) < WEEKLY:
            weeks.append(week)
            keep.add(path)
    removed = []
    for path in backups:
        if path not in keep:
            path.unlink()
            Path(str(path) + ".json").unlink(missing_ok=True)
            removed.append(path.name)
    purged = {}
    for path in sorted(keep, key=_stamp):
        manifest = _manifest(path)
        if (manifest.get("journal_entries") == len(entries) and
                manifest.get("suppression_entries", 0) == len(suppressions)):
            continue
        with tempfile.TemporaryDirectory(dir=dest) as scratch:
            ws = _open_copy(path, scratch)
            erased = _apply(ws, entries, suppressions)
            flat = _close_flat(ws)
            os.replace(flat, path)
        _write_manifest(path, SCHEMA_VERSION, manifest["created_at"], len(entries), len(suppressions))
        if erased:
            purged[path.name] = erased
    return {"kept": sorted(p.name for p in keep), "removed": removed, "purged": purged}


def restore(root, backup_path):
    """Replace the workspace database with a backup. The live workspace must be closed.

    Order: validate manifest and schema, migrate forward, re-apply the deletion journal, turn
    every in-flight attempt into *_unknown and set the stop flag so nothing executes before
    reconciliation, then swap the file in."""
    from .workspace import Workspace

    root = Path(root).resolve()
    manifest = _manifest(backup_path)
    live = Workspace(root)
    try:
        sync_journal(live)
    finally:
        live.close()
    from .suppression import journal as suppression_journal

    entries, suppressions = journal(root), suppression_journal(root)
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        ws = _open_copy(backup_path, scratch)
        try:
            purged = _apply(ws, entries, suppressions)
            with ws.store.transaction():
                unknown = [r["id"] for r in ws.db.execute("SELECT id FROM attempts WHERE state='in_flight'")]
                now = utcnow()
                for action_id in unknown:
                    ws.db.execute("UPDATE attempts SET state='unknown',updated_at=? WHERE id=?", (now, action_id))
                    ws.store.audit("attempt_unknown", action_id)
                ws.db.execute("INSERT INTO controls VALUES ('stop','1') ON CONFLICT(name) DO UPDATE SET value='1'")
                ws.store.audit("restored", Path(backup_path).name)
        except BaseException:
            ws.close()
            raise
        flat = _close_flat(ws)
        for suffix in ("-wal", "-shm"):
            (root / ("workspace.sqlite3" + suffix)).unlink(missing_ok=True)
        os.replace(flat, root / "workspace.sqlite3")
    return {"restored": Path(backup_path).name, "from_schema": manifest["schema_version"],
            "schema_version": SCHEMA_VERSION, "purged": purged, "unknown": unknown, "stopped": True,
            "next": "Reconcile every *_unknown action, then clear the stop flag."}
