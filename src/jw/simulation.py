"""JW-16: workspace-wide simulation (FR-SIM-01).

`--dry-run` runs the real command against a throwaway copy of the workspace and reports what it
would change: rows per table, audit events, and files it would write. The live workspace and
any requested output path are never touched. Simulated external actions never consume
authorisations or caps (see `Actions.simulate`) and every result is labelled `simulated`.
Provider writes (sending e-mail, labelling mail) cannot be simulated, so they are refused while a
simulation runs instead of reaching the real provider.
"""

from contextvars import ContextVar
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .contracts import require

LABEL = "SIMULATED: nothing was changed, written, sent or submitted."
OUTPUT_KEYS = ("output_path", "export_path")
OUTPUT_DIRS = ("to",)
JOURNALS = ("deletion-journal.jsonl", "suppression-journal.jsonl")
ACTIVE = ContextVar("jw_simulation_active", default=False)


def refuse_provider_write(what):
    """Fail closed when a provider write is attempted during a simulation."""
    require(not ACTIVE.get(), "unsupported_capability",
            "--dry-run cannot simulate " + what + "; nothing was sent or changed at the provider.")


def _counts(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                       "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}


def _audit_max(db):
    return db.execute("SELECT coalesce(max(rowid),0) FROM audit").fetchone()[0]


def run(root, command, data, dispatch):
    """Run `dispatch(ws, command, data)` on a copy of the workspace at `root`."""
    from .store import checked_database
    from .workspace import Workspace

    require(isinstance(data, dict), "invalid_schema", "Expected an object.")
    # Read-only: opening a Workspace here would migrate an older live database.
    database = checked_database(root)
    scratch = tempfile.mkdtemp(prefix="jw-sim-")
    try:
        copy = Path(scratch) / "ws"
        copy.mkdir()
        live = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(copy / "workspace.sqlite3")
        try:
            live.backup(target)
        finally:
            target.close()
            live.close()
        for name in JOURNALS:
            journal = database.parent / name
            if journal.is_file():
                shutil.copyfile(journal, copy / name)
        data = dict(data)
        files = {}
        for key in OUTPUT_KEYS + OUTPUT_DIRS:
            if key in data:
                require(isinstance(data[key], str), "invalid_schema", "Output path must be a string.")
                files[key] = data[key]
                data[key] = str(Path(scratch) / "out" / (Path(data[key]).name or "out"))
                (Path(scratch) / "out").mkdir(exist_ok=True)
        ws = Workspace(copy)
        active = ACTIVE.set(True)
        try:
            before, mark = _counts(ws.db), _audit_max(ws.db)
            result = dispatch(ws, command, data)
            after = _counts(ws.db)
            events = [r[0] for r in ws.db.execute("SELECT kind FROM audit WHERE rowid>? ORDER BY rowid", (mark,))]
        finally:
            ACTIVE.reset(active)
            ws.close()
        effects = {t: after[t] - before.get(t, 0) for t in after if after[t] != before.get(t, 0)}
        would_write = [path for key, path in files.items()]
        return {"simulated": True, "label": LABEL, "result": result, "effects": {
            "rows": effects, "audit": events, "files": would_write, "external_actions": []}}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
