"""JW-14: mailbox sync, message matching and Sent-folder reconciliation (FR-SYN-01, FR-SYN-02,
FR-EML-04 reply/bounce handling, FR-RES-03 evidence).

No mail provider is wired in. A provider adapter fetches changes since `checkpoint()` and hands
them over as plain message dicts; everything after the fetch happens here and is provider-free.

Rules that hold whatever the adapter:
- A message attaches to an application only through a matching signal, strongest first: the
  thread of a sent action, the action ID quoted back (`X-JW-Action-Id`), the requisition ID, then
  company plus role in a time window. "Latest application at that company" is never a match;
  anything weaker goes to the review queue.
- Each message is one transaction and advances the checkpoint, so a fetch that fails part way
  resumes after the last processed message. Re-running sync creates no duplicate events.
- Only hashes of the sender and subject, the sender domain and a bounded excerpt are stored.
- A reply cancels scheduled follow-ups; an opt-out suppresses the sender; a bounce suppresses
  the address the matched action went to. Auto-replies change nothing.
- Sent-folder reconciliation turns an `unknown` attempt into accepted only when a sent message
  carries its action ID. Finding nothing leaves it unknown (JW-12).
"""

import hashlib
import json
import re

from .contracts import fields, instant, require, string, utcnow

CLASSES = ("acknowledgement", "rejection", "interview_invite", "assessment", "offer", "auto_reply", "bounce",
           "opt_out", "other")
THRESHOLD = 0.75
EXCERPT = 200
WINDOW_DAYS = 180
SIGNAL_CONFIDENCE = {"thread": 0.99, "action_id": 0.97, "requisition": 0.9, "company_role": 0.8}
ACTION_ID = re.compile(r"X-JW-Action-Id:\s*(act_[A-Za-z0-9_-]{1,80})", re.I)
# Order matters: the first rule that fires wins ("unfortunately ... interview" is a rejection).
RULES = (
    ("bounce", r"delivery status notification|undeliverable|delivery has failed|address not found|mail delivery failed"),
    ("auto_reply", r"out of (?:the )?office|automatic reply|auto-?reply|away from my desk"),
    # A footer "unsubscribe" link is in nearly every recruiter mail: only a person asking counts.
    ("opt_out", r"(?:please )?unsubscribe me|remove me|do not contact|don't contact|stop (?:e-?mailing|contacting)"),
    ("offer", r"pleased to offer|offer letter|extend an offer"),
    ("rejection", r"unfortunately|not (?:be )?moving forward|other candidates|regret to inform|decided not to proceed"),
    ("assessment", r"assessment|coding challenge|take-home|online test"),
    # The bare word "interview" is in newsletters and prep courses; an invite asks to meet.
    ("interview_invite", r"invite you (?:to|for) (?:an? )?(?:interview|call|chat)|interview (?:invitation|invite)|"
                         r"schedule (?:an?|your) interview|schedule a (?:call|chat)|availability for (?:a|an) "
                         r"(?:call|interview)|like to interview you"),
    ("acknowledgement", r"received your application|thank you for applying|thanks for applying|application received|"
                        r"application was sent|submit(?:ting)? your application|thank you for your interest"),
)
BOUNCE_SENDERS = ("mailer-daemon@", "postmaster@")
MESSAGE_FIELDS = {"message_id", "thread_id", "history_id", "from", "subject", "body", "received_at"}


def _sha(text):
    return hashlib.sha256(text.strip().casefold().encode("utf-8")).hexdigest()


def _norm(text):
    return " ".join(str(text).split()).casefold()


def classify(sender, subject, body):
    text = _norm(subject + "\n" + body)
    if sender.casefold().startswith(BOUNCE_SENDERS):
        return "bounce"
    for name, pattern in RULES:
        if re.search(pattern, text):
            return name
    return "other"


def _message(raw):
    fields(raw, MESSAGE_FIELDS, {"references"})
    for key in ("message_id", "thread_id"):
        string(raw[key], 200)
    string(raw["from"], 320)
    require("@" in raw["from"], "invalid_schema", "Sender must be an e-mail address.")
    string(raw["subject"], 2000)
    require(isinstance(raw["body"], str) and len(raw["body"]) <= 100_000, "invalid_schema", "Body is bounded text.")
    require(type(raw["history_id"]) is int and raw["history_id"] > 0, "invalid_schema", "history_id is a positive integer.")
    instant(raw["received_at"])
    references = raw.get("references", [])
    require(isinstance(references, list) and len(references) <= 50, "invalid_schema", "references is a list.")
    for item in references:
        string(item, 200)
    return raw


class MailSync:
    def __init__(self, executor):
        self.ex = executor
        self.ws = executor.actions.ws
        self.db = self.ws.db
        self.store = self.ws.store
        self._journal = []

    def checkpoint(self):
        row = self.db.execute("SELECT history_id FROM mail_checkpoint").fetchone()
        return row["history_id"] if row else 0

    def sync(self, messages):
        """Process fetched messages in history order; returns the per-classification counts."""
        require(isinstance(messages, list) and len(messages) <= 5000, "invalid_schema", "Expected a list of messages.")
        report = {"scanned": 0, "duplicate": 0, "matched": 0, "review": 0, "ignored": 0,
                  "classes": {name: 0 for name in CLASSES}}
        for raw in sorted((_message(m) for m in messages), key=lambda m: m["history_id"]):
            report["scanned"] += 1
            outcome = self._one(raw)
            self._flush()
            report[outcome[0]] += 1
            if outcome[1]:
                report["classes"][outcome[1]] += 1
        report["checkpoint"] = self.checkpoint()
        return report

    def _one(self, m):
        with self.store.transaction():
            # Gmail history IDs are shared and not ordered per message, so the checkpoint is a cursor
            # only; the message ID alone decides a duplicate.
            if self.db.execute("SELECT 1 FROM mail_events WHERE message_id=?", (m["message_id"],)).fetchone():
                self._advance(m["history_id"])
                return ("duplicate", None)
            sender = _sha(m["from"])
            kind = classify(m["from"], m["subject"], m["body"])
            if self.db.execute("SELECT 1 FROM mail_ignored_senders WHERE sender_sha256=?", (sender,)).fetchone():
                self._insert(m, sender, kind, 0.0, None, None, [], "ignored")
                self._advance(m["history_id"])
                return ("ignored", kind)
            job_id, attempt, signals, candidates = self._match(m)
            confidence = SIGNAL_CONFIDENCE[signals[0]] if signals else 0.0
            if job_id and confidence >= THRESHOLD and kind != "other":
                self._insert(m, sender, kind, confidence, job_id, attempt, signals, "attached")
                self._effects(m, kind, job_id, attempt)
                result = "matched"
            elif job_id and kind == "other":
                self._insert(m, sender, kind, confidence, job_id, attempt, signals, "attached")
                result = "matched"
            else:
                self._insert(m, sender, kind, confidence, None, attempt, candidates, "review")
                result = "review"
            self._advance(m["history_id"])
        return (result, kind)

    def _advance(self, history_id):
        self.db.execute("INSERT INTO mail_checkpoint VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE SET "
                        "history_id=max(history_id, excluded.history_id), updated_at=excluded.updated_at",
                        (history_id, utcnow()))

    def _insert(self, m, sender, kind, confidence, job_id, attempt, signals, state):
        now = utcnow()
        domain = m["from"].rsplit("@", 1)[1].strip().casefold()[:253]
        self.db.execute("INSERT INTO mail_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (m["message_id"], m["thread_id"], m["history_id"], sender, domain, _sha(m["subject"]),
                         " ".join(m["body"].split())[:EXCERPT], kind, confidence, job_id, attempt,
                         json.dumps(signals), state, instant(m["received_at"]).isoformat(), now, now))
        self.store.audit("mail_" + state, m["message_id"])

    def _attempt_job(self, attempt_id):
        row = self.db.execute("SELECT e.job_id FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id "
                              "JOIN action_envelopes e ON e.id=z.envelope_id WHERE a.id=?", (attempt_id,)).fetchone()
        return row["job_id"] if row else None

    def _match(self, m):
        """(job_id, attempt_id, signals, ranked candidates). Strongest signal first; never a default."""
        refs = [m["thread_id"], *m.get("references", [])]
        marks = ",".join("?" * len(refs))
        row = self.db.execute(f"SELECT id FROM attempts WHERE channel='email' AND state IN ('accepted','unknown') "
                              f"AND provider_ref IN ({marks}) ORDER BY created_at LIMIT 1", refs).fetchone()
        if row and (job := self._attempt_job(row["id"])):
            return job, row["id"], ["thread"], []
        for action_id in ACTION_ID.findall(m["body"]):
            row = self.db.execute("SELECT id FROM attempts WHERE id=?", (action_id,)).fetchone()
            if row and (job := self._attempt_job(row["id"])):
                return job, row["id"], ["action_id"], []
        text = _norm(m["subject"] + "\n" + m["body"])
        received = instant(m["received_at"])
        jobs = [(r["id"], json.loads(r["data"])) for r in self.db.execute("SELECT id, data FROM jobs ORDER BY id")]
        by_req = [jid for jid, d in jobs if d.get("requisition") and _norm(d["requisition"]) in text]
        if len(by_req) == 1:
            return by_req[0], None, ["requisition"], []
        domain = m["from"].rsplit("@", 1)[1].casefold()
        at_company = [(jid, d) for jid, d in jobs
                      if _norm(d["company"]) in text or _norm(d["company"]).replace(" ", "") in domain]
        in_window = [(jid, d) for jid, d in at_company if self._contacted_within(jid, received)]
        by_role = [jid for jid, d in in_window if _norm(d["title"]) in text]
        if len(by_role) == 1:
            return by_role[0], None, ["company_role"], []
        ranked = sorted({jid for jid, _ in at_company}, key=lambda jid: (jid not in by_role, jid not in
                        {j for j, _ in in_window}, jid))
        return None, None, [], [{"job_id": jid, "signals": [s for s, hit in (
            ("company", True), ("window", jid in {j for j, _ in in_window}), ("role", jid in by_role)) if hit]}
            for jid in ranked]

    def _contacted_within(self, job_id, received):
        """An action or outcome for the job before the message, inside the window; no contact means no window."""
        rows = self.db.execute("SELECT a.created_at FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id "
                               "JOIN action_envelopes e ON e.id=z.envelope_id WHERE e.job_id=? UNION ALL "
                               "SELECT effective_at FROM outcomes WHERE job_id=?", (job_id, job_id)).fetchall()
        return any(0 <= (received - instant(r[0])).days <= WINDOW_DAYS for r in rows)

    def _effects(self, m, kind, job_id, attempt_id):
        """Reply cancels follow-ups; opt-out and bounce suppress. Runs inside the message transaction."""
        from .suppression import address_key, company_key

        if kind == "auto_reply":
            return
        if kind in ("opt_out", "bounce"):
            address = m["from"] if kind == "opt_out" else (
                self.store.one("attempts", attempt_id)["destination"] if attempt_id else None)
            if address:
                entry = {"address_sha256": address_key(address), "company": company_key(None),
                         "reason": "opt_out" if kind == "opt_out" else "hard_bounce", "at": utcnow()}
                self.db.execute("INSERT OR IGNORE INTO suppressions VALUES (?,?,?,?)",
                                (entry["address_sha256"], entry["company"], entry["reason"], entry["at"]))
                self.store.audit("address_suppressed", entry["address_sha256"][:16])
                self._journal.append(entry)
        reason = "suppressed" if kind in ("opt_out", "bounce") else "reply"
        rows = self.db.execute("SELECT id FROM followups WHERE state='scheduled' AND (job_id=? OR attempt_id=?)",
                               (job_id, attempt_id)).fetchall()
        for row in rows:
            self.db.execute("UPDATE followups SET state='cancelled',reason=?,updated_at=? WHERE id=?",
                            (reason, utcnow(), row["id"]))
            self.store.audit("followup_cancelled", row["id"])

    def _flush(self):
        """The suppression row commits with its message; the journal line (JW-13) follows the commit."""
        from .suppression import _append

        pending, self._journal = self._journal, []
        for entry in pending:
            _append(self.store.root, entry)

    def review_queue(self):
        return [{"message_id": r["message_id"], "classification": r["classification"],
                 "sender_domain": r["sender_domain"], "received_at": r["received_at"],
                 "candidates": json.loads(r["signals"])}
                for r in self.db.execute("SELECT * FROM mail_events WHERE state='review' ORDER BY received_at, message_id")]

    def _queued(self, message_id):
        string(message_id, 200)
        row = self.db.execute("SELECT * FROM mail_events WHERE message_id=?", (message_id,)).fetchone()
        require(row is not None, "not_found", "Message not found.")
        require(row["state"] == "review", "not_in_review", "The message is not waiting for review.")
        return row

    def assign(self, message_id, job_id):
        """The candidate attaches a queued message to an application; its effects apply as for a match."""
        with self.store.transaction():
            row = self._queued(message_id)
            self.store.one("jobs", job_id)
            self.db.execute("UPDATE mail_events SET state='attached',job_id=?,signals=?,confidence=1.0,updated_at=? "
                            "WHERE message_id=?", (job_id, json.dumps(["candidate"]), utcnow(), message_id))
            self.store.audit("mail_assigned", message_id)
            # The sender address is not stored, so a queued opt-out is suppressed by the candidate explicitly.
            if row["classification"] not in ("auto_reply", "other", "opt_out"):
                self._effects(None, row["classification"], job_id, row["attempt_id"])
        self._flush()
        return {"message_id": message_id, "state": "attached", "job_id": job_id}

    def dismiss(self, message_id, not_job_related=False):
        """Dismiss one message; `not_job_related` also ignores every later message from that sender."""
        with self.store.transaction():
            row = self._queued(message_id)
            state = "not_job_related" if not_job_related else "dismissed"
            self.db.execute("UPDATE mail_events SET state=?,updated_at=? WHERE message_id=?", (state, utcnow(), message_id))
            if not_job_related:
                self.db.execute("INSERT OR IGNORE INTO mail_ignored_senders VALUES (?,?)", (row["sender_sha256"], utcnow()))
            self.store.audit("mail_" + state, message_id)
        return {"message_id": message_id, "state": state}

    def reconcile_sent(self, token, action_id, sent_messages):
        """Search the Sent folder for the action ID. Found: accepted with that message as evidence.
        Nothing found: the attempt stays unknown and is never resent."""
        require(isinstance(sent_messages, list) and len(sent_messages) <= 5000, "invalid_schema",
                "Expected a list of sent messages.")
        for raw in sent_messages:
            fields(raw, {"message_id", "headers"}, {"thread_id"})
            string(raw["message_id"], 200)
            require(isinstance(raw["headers"], dict), "invalid_schema", "headers is an object.")
            if raw["headers"].get("X-JW-Action-Id") == action_id:
                return self.ex.reconcile(token, action_id, "found", provider_ref=raw.get("thread_id", raw["message_id"]))
        return self.ex.reconcile(token, action_id, "not_found")
