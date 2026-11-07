"""JW-15: follow-ups and their race contracts (FR-EML-04).

A follow-up is scheduled from an accepted e-mail, due `followup_days` later, at most
`max_followups` per original. It still needs its own envelope and approval to send.

Races are settled by the database's write lock, not by timing:
- Cancellation (reply, outcome change, candidate request, suppression) and reservation are
  each one IMMEDIATE transaction. Whichever commits first wins; the loser gets a stable code.
- Reservation re-checks, inside the executor's transaction, that the follow-up is still
  scheduled and due, that no outcome was recorded after it was scheduled, and that the address
  is not suppressed. It runs before the authorisation is spent, so a refused follow-up leaves the
  approval unused.
- A reserved follow-up cannot be cancelled: the send is already under way and its outcome is
  recorded on the attempt (accepted, failed or unknown), like any other action.
"""

from datetime import timedelta

from .contracts import instant, require, utcnow

FOLLOWUP_DAYS = 7
MAX_FOLLOWUPS = 1
REASONS = ("reply", "outcome_change", "candidate_request", "suppressed")


class Followups:
    def __init__(self, executor):
        self.ex = executor
        self.ws = executor.actions.ws
        self.db = self.ws.db

    def schedule(self, action_id, days=FOLLOWUP_DAYS, max_followups=MAX_FOLLOWUPS):
        require(type(days) is int and 1 <= days <= 60 and type(max_followups) is int and 0 <= max_followups <= 3,
                "invalid_schema", "followup_days is 1..60 and max_followups 0..3.")
        with self.ws.store.transaction():
            attempt = self.ws.store.one("attempts", action_id)
            require(attempt["channel"] == "email" and attempt["state"] == "accepted", "followup_not_allowed",
                    "Only an accepted e-mail gets a follow-up.")
            seq = self.db.execute("SELECT count(*) FROM followups WHERE attempt_id=?", (action_id,)).fetchone()[0] + 1
            require(seq <= max_followups, "followup_limit", "The follow-up limit for this e-mail is reached.")
            job = self.db.execute("SELECT e.job_id FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id "
                                  "JOIN action_envelopes e ON e.id=z.envelope_id WHERE a.id=?", (action_id,)).fetchone()
            from .workspace import identifier

            followup_id = identifier("fup")
            now = utcnow()
            due = (instant(attempt["updated_at"]) + timedelta(days=days)).isoformat()
            self.db.execute("INSERT INTO followups VALUES (?,?,?,?,?,?,'scheduled',NULL,NULL,?,?)",
                            (followup_id, action_id, job["job_id"] if job else None, attempt["destination"], seq,
                             due, now, now))
            self.ws.store.audit("followup_scheduled", followup_id)
        return {"followup_id": followup_id, "due_at": due, "seq": seq, "state": "scheduled"}

    def cancel(self, followup_id, reason):
        require(reason in REASONS, "invalid_schema", "Reason is reply, outcome_change, candidate_request or suppressed.")
        with self.ws.store.transaction():
            row = self.ws.store.one("followups", followup_id)
            require(row["state"] != "reserved", "followup_already_sending",
                    "The follow-up is already being sent; its outcome is tracked on the attempt.")
            if row["state"] == "scheduled":
                self.db.execute("UPDATE followups SET state='cancelled',reason=?,updated_at=? WHERE id=?",
                                (reason, utcnow(), followup_id))
                self.ws.store.audit("followup_cancelled", followup_id)
        return {"followup_id": followup_id, "state": "cancelled", "reason": row["reason"] or reason}

    def _invalidated(self, row):
        """Why a scheduled follow-up must not go out, or None. Runs inside a transaction."""
        from .suppression import suppressed

        if row["job_id"] and self.db.execute("SELECT 1 FROM outcomes WHERE job_id=? AND recorded_at>?",
                                             (row["job_id"], row["created_at"])).fetchone():
            return "outcome_change"
        company = None
        if row["job_id"]:
            import json
            company = json.loads(self.ws.store.one("jobs", row["job_id"])["data"]).get("company")
        if suppressed(self.ws, row["destination"], company):
            return "suppressed"
        return None

    def due(self, at=None):
        """Scheduled follow-ups now due. Invalidated ones are cancelled here, with their reason."""
        now = instant(at or utcnow())
        ready, cancelled = [], []
        with self.ws.store.transaction():
            for row in self.db.execute("SELECT * FROM followups WHERE state='scheduled' ORDER BY due_at").fetchall():
                reason = self._invalidated(row)
                if reason:
                    self.db.execute("UPDATE followups SET state='cancelled',reason=?,updated_at=? WHERE id=?",
                                    (reason, utcnow(), row["id"]))
                    self.ws.store.audit("followup_cancelled", row["id"])
                    cancelled.append({"followup_id": row["id"], "reason": reason})
                elif instant(row["due_at"]) <= now:
                    ready.append({"followup_id": row["id"], "destination": row["destination"], "due_at": row["due_at"]})
        return {"due": ready, "cancelled": cancelled}

    def reserve(self, token, followup_id, auth_id, content, attachments=()):
        row = self.ws.store.one("followups", followup_id)
        db, ws = self.db, self.ws

        def guard():
            current = ws.store.one("followups", followup_id)
            if current["state"] == "cancelled":
                return ("followup_cancelled", "The follow-up was cancelled (" + str(current["reason"]) + ").")
            if current["state"] == "reserved":
                return ("followup_already_sending", "The follow-up is already being sent.")
            if instant(utcnow()) < instant(current["due_at"]):
                return ("followup_not_due", "The follow-up is not due until " + current["due_at"] + ".")
            reason = self._invalidated(current)
            if reason:
                db.execute("UPDATE followups SET state='cancelled',reason=?,updated_at=? WHERE id=?",
                           (reason, utcnow(), followup_id))
                return ("followup_cancelled", "The follow-up was cancelled (" + reason + ").")
            return None

        def commit(action_id):
            db.execute("UPDATE followups SET state='reserved',action_id=?,updated_at=? WHERE id=?",
                       (action_id, utcnow(), followup_id))
            ws.store.audit("followup_reserved", followup_id)

        guard.commit = commit
        return self.ex.reserve(token, auth_id, "email", row["destination"], content, attachments, guard=guard)
