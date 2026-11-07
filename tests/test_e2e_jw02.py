"""E2E JW-02: `mail-sync` through the real CLI with a replay mailbox, and a demo-Gmail send with a
lost response reconciled from the Sent folder in a later process."""

import json

from e2e_support import E2E

SEND = """
from jw.actions import Actions
from jw.execution import Executor
from jw.gmail import DemoGmail, GmailAdapter
actions = Actions(ws)
actions.set_mode("email", "approve_each_action")
email = {"subject": "Platform Engineer application", "body": "Hello."}
env = actions.create_envelope("email", "talent@acme.example", email, job_id=values["job"])
auth = actions.approve(env["envelope_id"])["authorisation_id"]
ex = Executor(actions)
token = ex.acquire("w")["token"]
gmail = DemoGmail()
gmail.send_fault = "timeout"
adapter = GmailAdapter(ex, gmail, allowed=("read", "send"))
first = adapter.send(token, auth, "talent@acme.example", email)
again = None
try:
    adapter.send(token, auth, "talent@acme.example", email)
except Exception as exc:
    again = exc.code
settled = adapter.reconcile(token, first["action_id"])
print(json.dumps({"first": first["state"], "again": again, "settled": settled["state"],
                  "sends": gmail.calls.count("send")}))
"""


class GmailE2E(E2E):
    def test_replay_sync_is_idempotent_and_review_queue_is_visible(self):
        self.profile()
        self.ok("job-add", {"company": "Acme", "title": "Platform Engineer", "description": "D", "requirements": []})
        replay = self.dir / "mail.json"
        replay.write_text(json.dumps([
            {"message_id": "r1", "thread_id": "t1", "history_id": 11, "from": "talent@acme.example",
             "subject": "Thank you for applying", "body": "We received your application.",
             "received_at": "2026-11-01T10:00:00+00:00"},
            {"message_id": "r2", "thread_id": "t2", "history_id": 12, "from": "news@talent.example",
             "subject": "AI has changed the interview game", "body": "Webinar. Unsubscribe here.",
             "received_at": "2026-11-02T10:00:00+00:00"}]), encoding="utf-8")
        first = self.ok("mail-sync", {"transport": "replay", "path": str(replay)})
        self.assertEqual(("rebuild", "complete", 2), (first["mode"], first["state"], first["fetched"]))
        second = self.ok("mail-sync", {"transport": "replay", "path": str(replay)})
        self.assertEqual(("history", 0), (second["mode"], second["fetched"]))
        review = self.ok("mail-review", {})["review"]
        self.assertEqual({"acknowledgement", "other"}, {r["classification"] for r in review})

    def test_cli_refuses_send_and_unconfigured_http(self):
        self.fails("invalid_schema", "mail-sync", {"transport": "replay", "path": "x", "allowed": ["send"]})
        self.fails("not_configured", "mail-sync", {"transport": "http", "token_env": "JW_TEST_UNSET_TOKEN"})
        self.fails("unsupported_capability", "send")

    def test_lost_send_is_never_resent_and_reconciles_from_sent(self):
        self.profile()
        job = self.ok("job-add", {"company": "Acme", "title": "Platform Engineer", "description": "D",
                                  "requirements": []})["job_id"]
        result = self.py(SEND, job=job)
        self.assertEqual({"first": "send_unknown", "again": "unresolved_unknown", "settled": "sent_accepted",
                          "sends": 1}, result)
