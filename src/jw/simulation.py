"""JW-16: workspace-wide simulation (FR-SIM-01).

`--dry-run` runs the real command against a throwaway copy of the workspace and reports what it
would change: rows per table, audit events, and files it would write. The live workspace and
any requested output path are never touched. Simulated external actions never consume
authorisations or caps (see `Actions.simulate`) and every result is labelled `simulated`.
"""

from pathlib import Path
import shutil
import sqlite3
import tempfile

from .contracts import require

LABEL = "SIMULATED: nothing was changed, written, sent or submitted."
OUTPUT_KEYS = ("output_path",)


def _counts(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                       "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def _audit_max(db):
    return db.execute("SELECT coalesce(max(rowid),0) FROM audit").fetchone()[0]


def run(root, command, data, dispatch):
    """Run `dispatch(ws, command, data)` on a copy of the workspace at `root`."""
    from .workspace import Workspace

    live = Workspace(root)
    scratch = tempfile.mkdtemp(prefix="jw-sim-")
    try:
        copy = Path(scratch) / "ws"
        copy.mkdir()
        target = sqlite3.connect(copy / "workspace.sqlite3")
        try:
            live.db.backup(target)
        finally:
            target.close()
            live.close()
        journal = Path(root) / "deletion-journal.jsonl"
        if journal.is_file():
            shutil.copyfile(journal, copy / journal.name)
        data = dict(data)
        files = {}
        for key in OUTPUT_KEYS:
            if key in data:
                require(isinstance(data[key], str), "invalid_schema", "Output path must be a string.")
                files[key] = data[key]
                data[key] = str(Path(scratch) / "out" / Path(data[key]).name)
                (Path(scratch) / "out").mkdir(exist_ok=True)
        ws = Workspace(copy)
        try:
            before, mark = _counts(ws.db), _audit_max(ws.db)
            result = dispatch(ws, command, data)
            after = _counts(ws.db)
            events = [r[0] for r in ws.db.execute("SELECT kind FROM audit WHERE rowid>? ORDER BY rowid", (mark,))]
        finally:
            ws.close()
        effects = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
        would_write = [path for key, path in files.items()]
        return {"simulated": True, "label": LABEL, "result": result, "effects": {
            "rows": effects, "audit": events, "files": would_write, "external_actions": []}}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
