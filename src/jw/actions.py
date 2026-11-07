"""JW-11: immutable action envelopes and hash-bound approvals (FR-AUT-01, FR-AUT-03, FR-AUT-05).

No provider exists. `claim` is the guard an executor must pass immediately before a provider
call: it recomputes every hash from what the executor is about to send and refuses on any
mismatch, expiry, revocation, stop flag or draft-only channel. Nothing here sends anything.
"""

from datetime import timedelta
import hashlib
import json

from .contracts import canonical, digest, fields, instant, require, string, utcnow
from .workspace import identifier

# One channel's authorisation never covers another: each channel has exactly one action type.
CHANNELS = {"email": "send_email", "comment": "post_comment", "ats": "submit_application"}
MODES = ("draft_only", "approve_each_action", "authorized_campaign")
MAX_APPROVAL_HOURS = 14 * 24
CONTENT_FIELDS = {"email": {"subject", "body"}, "comment": {"body"}, "ats": {"answers"}}


def content_hash(channel, content):
    """Subject + body, comment body, or application answers, in canonical form."""
    fields(content, CONTENT_FIELDS[channel])
    if channel == "ats":
        require(isinstance(content["answers"], dict) and content["answers"], "invalid_schema",
                "Application answers must be a non-empty object.")
        for key, value in content["answers"].items():
            string(key, 200)
            string(value, 5000)
    else:
        for key in CONTENT_FIELDS[channel]:
            string(content[key], 20000 if key == "body" else 300)
    return digest(content)


def attachment_hashes(attachments):
    require(isinstance(attachments, list) and len(attachments) <= 10 and
            all(isinstance(item, bytes) and item for item in attachments),
            "invalid_schema", "Attachments are up to 10 non-empty byte strings.")
    return [hashlib.sha256(item).hexdigest() for item in attachments]


class Actions:
    def __init__(self, workspace):
        self.ws = workspace
        self.store = workspace.store
        self.db = workspace.db

    def _channel(self, channel):
        require(isinstance(channel, str) and channel in CHANNELS, "invalid_schema", "Unknown channel.")
        return channel

    def mode(self, channel):
        row = self.db.execute("SELECT mode FROM channel_modes WHERE channel=?", (self._channel(channel),)).fetchone()
        return row["mode"] if row else "draft_only"

    def set_mode(self, channel, mode):
        require(mode in MODES, "invalid_schema", "Mode is draft_only, approve_each_action or authorized_campaign.")
        with self.store.transaction():
            self.db.execute("INSERT INTO channel_modes VALUES (?,?,?) ON CONFLICT(channel) DO UPDATE SET "
                            "mode=excluded.mode, updated_at=excluded.updated_at", (self._channel(channel), mode, utcnow()))
            self.store.audit("channel_mode_" + mode, channel)
        return {"channel": channel, "mode": mode}

    def profile_version(self):
        row = self.db.execute("SELECT * FROM profile").fetchone()
        require(row is not None and row["published"] == 1, "profile_unpublished", "Publish the corrected profile first.")
        return digest(dict(row))

    def create_envelope(self, channel, destination, content, attachments=()):
        """Freeze one action. Envelopes have no update path: an edit is a new envelope."""
        channel = self._channel(channel)
        string(destination, 2000)
        hashes = attachment_hashes(list(attachments))
        hashed = content_hash(channel, content)
        with self.store.transaction():
            envelope_id = identifier("env")
            self.db.execute("INSERT INTO action_envelopes VALUES (?,?,?,?,?,?,?,?,?)",
                            (envelope_id, channel, CHANNELS[channel], destination, canonical(content),
                             hashed, canonical(hashes), self.profile_version(), utcnow()))
            self.store.audit("envelope_created", envelope_id)
        return {"envelope_id": envelope_id, "channel": channel, "action_type": CHANNELS[channel],
                "content_hash": hashed, "attachment_hashes": hashes}

    def approve(self, envelope_id, hours=24, creator="candidate"):
        require(type(hours) is int and 0 < hours <= MAX_APPROVAL_HOURS, "invalid_schema",
                "Approval lasts 1 hour to 14 days.")
        string(creator, 100)
        with self.store.transaction():
            envelope = self.store.one("action_envelopes", envelope_id)
            require(self.mode(envelope["channel"]) != "draft_only", "channel_draft_only",
                    "This channel is draft only; approvals are refused.")
            require(envelope["profile_version"] == self.profile_version(), "auth_hash_mismatch",
                    "The profile changed since this envelope was made; create a new one.")
            # Campaigns are not implemented: a campaign channel falls back to per-action approval (FR-AUT-02).
            auth_id = identifier("aut")
            now = utcnow()
            expires = (instant(now) + timedelta(hours=hours)).isoformat()
            self.db.execute("INSERT INTO authorisations VALUES (?,?,?,?,?,?,?,?,?,?,'active',?,NULL)",
                            (auth_id, envelope_id, envelope["channel"], envelope["action_type"],
                             envelope["destination"], envelope["content_hash"], envelope["attachment_hashes"],
                             envelope["profile_version"], expires, creator, now))
            self.store.audit("authorisation_created", auth_id)
        return {"authorisation_id": auth_id, "state": "active", "expires_at": expires,
                "approval": "approve_each_action"}

    def revoke(self, auth_id):
        with self.store.transaction():
            auth = self.store.one("authorisations", auth_id)
            require(auth["state"] == "active", "auth_not_active", "Only an active authorisation can be revoked.")
            self.db.execute("UPDATE authorisations SET state='revoked',ended_at=? WHERE id=?", (utcnow(), auth_id))
            self.store.audit("authorisation_revoked", auth_id)
        return {"authorisation_id": auth_id, "state": "revoked"}

    def stop(self):
        return self._set_stop(True)

    def resume(self):
        return self._set_stop(False)

    def _set_stop(self, on):
        with self.store.transaction():
            self.db.execute("INSERT INTO controls VALUES ('stop',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                            ("1" if on else "0",))
            self.store.audit("stop_on" if on else "stop_off", "controls")
        return {"stopped": on}

    def stopped(self):
        row = self.db.execute("SELECT value FROM controls WHERE name='stop'").fetchone()
        return row is not None and row["value"] == "1"

    def _end(self, auth_id, state, code, message):
        self.db.execute("UPDATE authorisations SET state=?,ended_at=? WHERE id=?", (state, utcnow(), auth_id))
        self.store.audit("authorisation_" + state, auth_id)
        return code, message

    def claim(self, auth_id, channel, destination, content, attachments=()):
        """The executor's last step before a provider call. Single use: success marks it used.

        A refusal that ends the authorisation (expiry, mismatch) is committed before the error
        is raised, so a retry cannot slip past it."""
        with self.store.transaction():
            failure = self.check_and_use(auth_id, channel, destination, content, attachments)
        if failure:
            require(False, *failure)
        return {"authorisation_id": auth_id, "state": "used", "provider_call": "not_performed",
                "detail": "No provider exists; the executor would call it now."}

    def check_and_use(self, auth_id, channel, destination, content, attachments=()):
        """Run inside the caller's transaction. Returns (code, message) on refusal, else None."""
        auth = self.store.one("authorisations", auth_id)
        if self.stopped():
            return ("stopped", "The stop flag is set; no provider call is made.")
        if auth["state"] != "active":
            return ("auth_" + auth["state"], "Authorisation is " + auth["state"] + "; no provider call is made.")
        if instant(utcnow()) >= instant(auth["expires_at"]):
            return self._end(auth_id, "expired", "auth_expired", "Authorisation expired; no provider call is made.")
        if self.mode(auth["channel"]) == "draft_only":
            return ("channel_draft_only", "This channel is draft only; no provider call is made.")
        channel = self._channel(channel)
        hashes = attachment_hashes(list(attachments))
        if (channel != auth["channel"] or destination != auth["destination"] or
                content_hash(channel, content) != auth["content_hash"] or
                hashes != json.loads(auth["attachment_hashes"]) or
                self.profile_version() != auth["profile_version"]):
            return self._end(auth_id, "invalid", "auth_hash_mismatch",
                             "What would be sent differs from what was approved; no provider call is made.")
        self.db.execute("UPDATE authorisations SET state='used',ended_at=? WHERE id=?", (utcnow(), auth_id))
        self.store.audit("authorisation_used", auth_id)
        return None
