"""JW-20: pause, resume, durable checkpoint and the application state reducer
(FR-RES-01..03, FR-TRK-01).

Resume order is fixed: clear the stop flag, take the lease with a new fencing token, verify the
pinned versions against the last checkpoint and end expired authorisations, reconcile every
`*_unknown` action, and only then report pending work. If anything is unknown, resume stops at
`reconcile_required` and lists it; no pending job is offered until it is resolved.

The reducer keeps preparation, channel and outcome states separate. Channels show only what an
attempt row proves; a channel with no attempt is `inactive` or `not_attempted`, never a receipt.
"""

import json
import os
from pathlib import Path

from .contracts import digest, instant, require, utcnow
from .execution import LABELS

CHECKPOINT = "progress.json"


def _write_atomic(path, data):
    # Write, fsync, then rename: a crash leaves either the old or the new file, never half of one.
    tmp = Path(str(path) + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(data, sort_keys=True, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


class Runs:
    def __init__(self, executor):
        self.ex = executor
        self.actions = executor.actions
        self.ws = executor.actions.ws
        self.db = self.ws.db

    def progress(self):
        tasks = self.db.execute("SELECT id, kind, job_id, state FROM tasks ORDER BY created_at, id").fetchall()
        attempts = self.db.execute("SELECT id, channel, state FROM attempts ORDER BY created_at, id").fetchall()
        unknown = [a["id"] for a in attempts if a["state"] == "unknown"]
        pending = [t["id"] for t in tasks if t["state"] == "needs_model"]
        stopped = self.actions.stopped()
        if unknown:
            step = "reconcile " + unknown[0]
        elif stopped:
            step = "resume"
        elif pending:
            step = "continue " + pending[0]
        else:
            step = "idle"
        return {"completed": [t["id"] for t in tasks if t["state"] == "completed"], "pending": pending,
                "blocked": [{"id": t["id"], "state": t["state"]} for t in tasks if t["state"].startswith("blocked")],
                "versions": self.ws.versions(), "action_ids": [a["id"] for a in attempts],
                "unresolved": unknown, "stopped": stopped, "next_safe_step": step, "at": utcnow()}

    def checkpoint(self):
        data = self.progress()
        _write_atomic(self.ws.store.root / CHECKPOINT, data)
        return data

    def last_checkpoint(self):
        path = self.ws.store.root / CHECKPOINT
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def pause(self):
        """Set the persistent stop flag and checkpoint. In-flight provider calls finish or become unknown."""
        self.actions.stop()
        return dict(self.checkpoint(), paused=True)

    def resume(self, holder, seconds=300):
        previous = self.last_checkpoint()
        self.actions.resume()
        lease = self.ex.acquire(holder, seconds)
        changed = sorted(k for k, v in self.ws.versions().items()
                         if previous is not None and previous["versions"].get(k) != v)
        expired = []
        with self.ws.store.transaction():
            now = utcnow()
            for row in self.db.execute("SELECT id, expires_at FROM authorisations WHERE state='active'").fetchall():
                if instant(now) >= instant(row["expires_at"]):
                    self.db.execute("UPDATE authorisations SET state='expired',ended_at=? WHERE id=?", (now, row["id"]))
                    self.ws.store.audit("authorisation_expired", row["id"])
                    expired.append(row["id"])
        progress = self.checkpoint()
        state = "reconcile_required" if progress["unresolved"] else "ready"
        return {"state": state, "token": lease["token"], "became_unknown": lease["unknown"],
                "versions_changed": changed, "authorisations_expired": expired,
                "unresolved": progress["unresolved"],
                "pending": [] if progress["unresolved"] else progress["pending"],
                "next_safe_step": progress["next_safe_step"]}


def reduce_application(ws, job_id):
    """One job's state, split into preparation, channels and outcome (FR-TRK-01)."""
    ws.store.one("jobs", job_id)
    tasks = ws.db.execute("SELECT id, kind, state FROM tasks WHERE job_id=?", (job_id,)).fetchall()
    verified = {r["task_id"] for r in ws.db.execute(
        "SELECT task_id FROM verifications WHERE status='mechanical_passed' AND task_id IN "
        "(SELECT id FROM tasks WHERE job_id=?)", (job_id,))}
    drafts = [t for t in tasks if t["kind"] in ("draft_cv", "draft_letter")]
    if any(t["id"] in verified for t in drafts):
        preparation = "mechanically_verified"
    elif any(t["state"] == "completed" for t in drafts):
        preparation = "drafted"
    elif any(t["state"] == "needs_model" for t in drafts):
        preparation = "drafting"
    elif any(t["state"].startswith("blocked") for t in drafts):
        preparation = "blocked"
    else:
        preparation = "not_started"
    channels = {}
    from .actions import Actions

    modes = Actions(ws)
    for channel in LABELS:
        rows = ws.db.execute("SELECT a.state FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id "
                             "JOIN action_envelopes e ON e.id=z.envelope_id WHERE a.channel=? AND e.job_id=? "
                             "ORDER BY a.created_at DESC", (channel, job_id)).fetchall()
        if rows:
            channels[channel] = LABELS[channel][rows[0]["state"]]
        else:
            channels[channel] = "inactive" if modes.mode(channel) == "draft_only" else "not_attempted"
    row = ws.db.execute("SELECT kind, effective_at FROM outcomes WHERE job_id=? ORDER BY effective_at DESC, "
                        "recorded_at DESC LIMIT 1", (job_id,)).fetchone()
    outcome = {"kind": row["kind"], "effective_at": row["effective_at"], "source": "manual"} if row else None
    state = {"job_id": job_id, "preparation": preparation, "channels": channels, "outcome": outcome}
    state["fingerprint"] = digest(state)
    return state

