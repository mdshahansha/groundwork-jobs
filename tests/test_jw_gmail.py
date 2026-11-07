"""JW-02: durable Gmail adapter against the demo transport (history, rebuild, crash, quota, labels, send)."""

import json
from pathlib import Path
import tempfile
import unittest

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.gmail import DemoGmail, GmailAdapter, ReplayGmail, normalize
from jw.workspace import Workspace

TO = "talent@acme.example"
CONTENT = {"subject": "Application: Platform Engineer", "body": "Hello, please find my application."}


class GmailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())
        text = "Built Python services."
        source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.ws.add_claim(source, 0, len(text))
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Acme", "title": "Platform Engineer", "description": "D",
                                    "requirements": []})["job_id"]
        self.actions = Actions(self.ws)
        self.actions.set_mode("email", "approve_each_action")
        self.ex = Executor(self.actions)
        self.token = self.ex.acquire("w", seconds=3600)["token"]
        self.gmail = DemoGmail(scopes=("gmail.modify",))

    def adapter(self, **kw):
        kw.setdefault("allowed", ("read", "label", "send"))
        return GmailAdapter(self.ex, self.gmail, **kw)

    def auth(self):
        envelope = self.actions.create_envelope("email", TO, CONTENT, job_id=self.job)
        return self.actions.approve(envelope["envelope_id"], hours=24)["authorisation_id"]

    def events(self):
        return self.ws.db.execute("SELECT count(*) FROM mail_events").fetchone()[0]

    def test_first_run_rebuilds_then_history_is_incremental_and_idempotent(self):
        self.gmail.deliver("news@other.example", "Weekly digest", "Nothing here.")
        first = self.adapter().sync()
        self.assertEqual(("rebuild", "complete", 1), (first["mode"], first["state"], first["fetched"]))
        self.gmail.deliver("a@other.example", "Hi", "One.")
        self.gmail.deliver("b@other.example", "Hi", "Two.")
        self.gmail.deliver("c@other.example", "Hi", "Three.")
        second = self.adapter().sync()
        self.assertEqual(("history", 3), (second["mode"], second["fetched"]))
        self.assertEqual(self.gmail.history_id, second["checkpoint"])
        third = self.adapter().sync()
        self.assertEqual((0, 4), (third["fetched"], self.events()))

    def test_expired_history_falls_back_to_full_rebuild_without_duplicates(self):
        self.gmail.deliver("a@other.example", "Hi", "One.")
        self.adapter().sync()
        self.gmail.deliver("b@other.example", "Hi", "Two.")
        self.gmail.expire_history = True
        report = self.adapter().sync()
        self.assertEqual(("rebuild", "complete"), (report["mode"], report["state"]))
        self.assertEqual(2, self.events())

    def test_crash_mid_batch_commits_nothing_partial_and_rerun_completes(self):
        self.adapter().sync()
        ids = [self.gmail.deliver("x%d@other.example" % i, "Hi", "Body %d." % i) for i in range(3)]
        before = self.ws.db.execute("SELECT history_id FROM mail_checkpoint").fetchone()[0]
        self.gmail.crash_on_get = {ids[1]}
        crashed = self.adapter().sync()
        self.assertEqual("failed_transient", crashed["state"])
        self.assertEqual(before, crashed["checkpoint"])
        rerun = self.adapter().sync()
        self.assertEqual(("complete", 3, 3), (rerun["state"], rerun["fetched"], self.events()))

    def test_provider_quota_pauses_and_keeps_progress(self):
        self.adapter().sync()
        for i in range(3):
            self.gmail.deliver("q%d@other.example" % i, "Hi", "Body.")
        self.gmail.quota_after = 1  # history page passes, first get is rate limited
        paused = self.adapter().sync()
        self.assertEqual(("paused_quota", 60), (paused["state"], paused["retry_after"]))
        self.gmail.quota_after = None
        self.assertEqual(3, self.adapter().sync()["fetched"])

    def test_local_budget_pauses_before_overspending(self):
        for i in range(5):
            self.gmail.deliver("b%d@other.example" % i, "Hi", "Body.")
        report = self.adapter(budget=12).sync()
        self.assertEqual("paused_budget", report["state"])
        self.assertLessEqual(report["units"], 12)

    def test_matched_mail_is_labelled_and_label_failure_is_counted_not_rolled_back(self):
        self.adapter().sync()
        auth = self.auth()
        sent = self.adapter().send(self.token, auth, TO, CONTENT)
        thread = self.ex.attempt(sent["action_id"])["provider_ref"]
        self.gmail.deliver(TO, "Re: Application", "Thank you for applying to Acme.", thread=thread)
        report = self.adapter().sync()
        self.assertEqual((1, 1), (report["matched"], report["labelled"]))
        self.gmail.deliver(TO, "Re: Application", "Unfortunately we will not proceed.", thread=thread)
        self.gmail.label_fault = True
        failed = self.adapter().sync()
        self.assertEqual((1, 1, "complete"), (failed["matched"], failed["label_failed"], failed["state"]))

    def test_read_only_scope_or_policy_refuses_before_any_call(self):
        self.gmail.scopes = {"gmail.readonly"}
        with self.assertRaises(WorkspaceError) as caught:
            self.adapter().send(self.token, self.auth(), TO, CONTENT)
        self.assertEqual("missing_scope", caught.exception.code)
        with self.assertRaises(WorkspaceError) as caught:
            GmailAdapter(self.ex, self.gmail, allowed=()).sync()
        self.assertEqual("policy_denied", caught.exception.code)
        self.assertEqual([], self.gmail.calls)

    def test_send_accepted_carries_action_id_header_and_body(self):
        result = self.adapter().send(self.token, self.auth(), TO, CONTENT)
        self.assertEqual("sent_accepted", result["state"])
        sent = [m for m in self.gmail.messages.values() if "SENT" in m["labelIds"]][0]
        headers = {h["name"]: h["value"] for h in sent["payload"]["headers"]}
        self.assertEqual(result["action_id"], headers["X-JW-Action-Id"])
        self.assertIn(result["action_id"], normalize(sent)["body"])

    def test_lost_response_is_unknown_never_resent_then_reconciled_from_sent(self):
        self.gmail.send_fault = "timeout"
        result = self.adapter().send(self.token, self.auth(), TO, CONTENT)
        self.assertEqual("send_unknown", result["state"])
        self.gmail.send_fault = None
        with self.assertRaises(WorkspaceError) as caught:
            self.adapter().send(self.token, self.auth(), TO, CONTENT)
        self.assertEqual("unresolved_unknown", caught.exception.code)
        self.assertEqual(1, self.gmail.calls.count("send"))
        self.assertEqual("sent_accepted", self.adapter().reconcile(self.token, result["action_id"])["state"])

    def test_unknown_with_nothing_in_sent_stays_unknown(self):
        self.gmail.send_fault = "timeout"
        result = self.adapter().send(self.token, self.auth(), TO, CONTENT)
        self.gmail.messages = {k: v for k, v in self.gmail.messages.items() if "SENT" not in v["labelIds"]}
        self.assertEqual("send_unknown", self.adapter().reconcile(self.token, result["action_id"])["state"])

    def test_provider_rejection_is_failed(self):
        self.gmail.send_fault = "rejected"
        self.assertEqual("send_failed", self.adapter().send(self.token, self.auth(), TO, CONTENT)["state"])

    def test_replay_transport_is_read_only(self):
        path = Path(self.temp.name) / "replay.json"
        path.write_text(json.dumps([{"message_id": "r1", "thread_id": "t1", "history_id": 5, "from": TO,
                                     "subject": "Thank you for applying", "body": "Platform Engineer at Acme.",
                                     "received_at": "2026-11-01T10:00:00+00:00"}]), encoding="utf-8")
        replay = GmailAdapter(self.ex, ReplayGmail(path), allowed=("read",))
        self.assertEqual(1, replay.sync()["fetched"])
        with self.assertRaises(WorkspaceError):
            GmailAdapter(self.ex, ReplayGmail(path), allowed=("read", "send")).send(self.token, self.auth(), TO, CONTENT)


if __name__ == "__main__":
    unittest.main()
