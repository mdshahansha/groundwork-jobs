"""JW-12: execution lease, fencing tokens, attempt reservation and uncertain-outcome recovery
(FR-RES-03, FR-EML-03, FR-APP-04 state shapes).

No provider exists. The executor holds the single lease, reserves an attempt (which spends the
authorisation and records the action ID) before any provider call, then records the outcome.
An attempt still in flight when its lease is superseded becomes `unknown`; an unknown attempt
is never resent and blocks its channel until reconciliation finds evidence either way. A search
that finds nothing is not proof of failure, so `not_found` leaves the attempt unknown.
"""

from datetime import timedelta

from .contracts import instant, require, string, utcnow
from .workspace import identifier

LEASE = "executor"
MAX_LEASE_SECONDS = 3600
# Generic states stored; each channel shows its own PRD vocabulary.
LABELS = {
    "email": {"in_flight": "sending", "accepted": "sent_accepted", "failed": "send_failed", "unknown": "send_unknown"},
    "comment": {"in_flight": "publishing", "accepted": "published", "failed": "publish_failed",
                "unknown": "publish_unknown"},
    "ats": {"in_flight": "submitting", "accepted": "submitted_unverified", "failed": "submit_failed",
            "unknown": "submission_unknown"},
}


class Executor:
    def __init__(self, actions):
        self.actions = actions
        self.store = actions.store
        self.db = actions.db

    def _seconds(self, seconds):
        require(type(seconds) is int and 0 < seconds <= MAX_LEASE_SECONDS, "invalid_schema",
                "Lease lasts 1 second to 1 hour.")
        return seconds

    def acquire(self, holder, seconds=300):
        """Take the lease with a new fencing token. In-flight attempts from older tokens become unknown."""
        string(holder, 100)
        seconds = self._seconds(seconds)
        with self.store.transaction():
            row = self.db.execute("SELECT * FROM leases WHERE name=?", (LEASE,)).fetchone()
            now = utcnow()
            if row is not None and row["holder"] != holder and instant(now) < instant(row["expires_at"]):
                held = True
            else:
                held = False
                token = (row["token"] if row else 0) + 1
                expires = (instant(now) + timedelta(seconds=seconds)).isoformat()
                self.db.execute("INSERT INTO leases VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                                "holder=excluded.holder, token=excluded.token, expires_at=excluded.expires_at",
                                (LEASE, holder, token, expires))
                stale = [r["id"] for r in self.db.execute(
                    "SELECT id FROM attempts WHERE state='in_flight' AND lease_token<?", (token,))]
                for action_id in stale:
                    self.db.execute("UPDATE attempts SET state='unknown',updated_at=? WHERE id=?", (now, action_id))
                    self.store.audit("attempt_unknown", action_id)
                self.store.audit("lease_acquired", holder)
        require(not held, "lease_held", "Another worker holds the lease.")
        return {"holder": holder, "token": token, "expires_at": expires, "unknown": stale}

    def _fence(self, token):
        row = self.db.execute("SELECT * FROM leases WHERE name=?", (LEASE,)).fetchone()
        require(type(token) is int and row is not None and row["token"] == token and
                instant(utcnow()) < instant(row["expires_at"]), "lease_lost",
                "This worker no longer holds the lease; its write is rejected.")

    def renew(self, token, seconds=300):
        seconds = self._seconds(seconds)
        with self.store.transaction():
            self._fence(token)
            expires = (instant(utcnow()) + timedelta(seconds=seconds)).isoformat()
            self.db.execute("UPDATE leases SET expires_at=? WHERE name=?", (expires, LEASE))
        return {"token": token, "expires_at": expires}

    def release(self, token):
        with self.store.transaction():
            self._fence(token)
            self.db.execute("UPDATE leases SET expires_at=? WHERE name=?", (utcnow(), LEASE))
            self.store.audit("lease_released", str(token))
        return {"released": token}

    def reserve(self, token, auth_id, channel, destination, content, attachments=()):
        """Record the attempt before the provider call; the returned action ID goes in the message header."""
        failure = None
        with self.store.transaction():
            self._fence(token)
            channel = self.actions._channel(channel)
            if self.db.execute("SELECT 1 FROM attempts WHERE channel=? AND state='unknown'", (channel,)).fetchone():
                failure = ("unresolved_unknown", "Reconcile the uncertain " + channel + " action before any other.")
            else:
                failure = self.actions.check_and_use(auth_id, channel, destination, content, attachments)
            if failure is None:
                action_id = identifier("act")
                now = utcnow()
                self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'in_flight',NULL,NULL,?,?)",
                                (action_id, auth_id, channel, destination, token, now, now))
                self.store.audit("attempt_in_flight", action_id)
        if failure:
            require(False, *failure)
        return {"action_id": action_id, "state": LABELS[channel]["in_flight"],
                "headers": {"X-JW-Action-Id": action_id}, "provider_call": "not_performed"}

    def _resolve(self, token, action_id, expected, state, provider_ref, evidence):
        with self.store.transaction():
            self._fence(token)
            attempt = self.store.one("attempts", action_id)
            require(attempt["state"] == expected, "attempt_not_" + expected,
                    "The attempt is " + attempt["state"] + ", not " + expected + ".")
            if expected == "in_flight":
                require(attempt["lease_token"] == token, "lease_lost", "The attempt belongs to an earlier lease.")
            if state == "accepted":
                string(provider_ref, 500)
            if state == "failed":
                string(evidence, 2000)
            self.db.execute("UPDATE attempts SET state=?,provider_ref=?,evidence=?,updated_at=? WHERE id=?",
                            (state, provider_ref, evidence, utcnow(), action_id))
            self.store.audit("attempt_" + state, action_id)
        return {"action_id": action_id, "state": LABELS[attempt["channel"]][state]}

    def record(self, token, action_id, outcome, provider_ref=None, evidence=None):
        """The provider answered (accepted / failed) or did not (unknown: timeout, dropped connection)."""
        require(outcome in ("accepted", "failed", "unknown"), "invalid_schema", "Outcome is accepted, failed or unknown.")
        return self._resolve(token, action_id, "in_flight", outcome, provider_ref, evidence)

    def reconcile(self, token, action_id, finding, provider_ref=None, evidence=None):
        """found: the provider has it. rejected: provider evidence it never happened. not_found: still unknown."""
        require(finding in ("found", "rejected", "not_found"), "invalid_schema", "Finding is found, rejected or not_found.")
        if finding == "not_found":
            with self.store.transaction():
                self._fence(token)
                attempt = self.store.one("attempts", action_id)
                require(attempt["state"] == "unknown", "attempt_not_unknown", "Only an unknown attempt is reconciled.")
                self.store.audit("reconcile_not_found", action_id)
            return {"action_id": action_id, "state": LABELS[attempt["channel"]]["unknown"],
                    "detail": "No result is not proof of failure; the action stays unknown and is not resent."}
        state = "accepted" if finding == "found" else "failed"
        return self._resolve(token, action_id, "unknown", state, provider_ref, evidence)

    def attempt(self, action_id):
        row = self.store.one("attempts", action_id)
        return {"action_id": action_id, "channel": row["channel"], "state": LABELS[row["channel"]][row["state"]],
                "provider_ref": row["provider_ref"]}
