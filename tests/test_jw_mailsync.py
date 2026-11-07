"""JW-14: mailbox sync, matching, review queue and Sent-folder reconciliation (T-SYN-01..03)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.followups import Followups
from jw.mailsync import MailSync, classify
from jw.suppression import journal, suppressed
from jw.workspace import Workspace

TO = "recruiter@acme.example"
FIRST = {"subject": "Application", "body": "Hello."}


def soon(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class MailSyncTests(unittest.TestCase):
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
        self.job_a = self.ws.add_job({"company": "Acme", "title": "Data Engineer", "description": "D",
                                      "requirements": [], "requisition": "REQ-1001"})["job_id"]
        self.job_b = self.ws.add_job({"company": "Acme", "title": "Platform Engineer", "description": "D",
                                      "requirements": []})["job_id"]
        self.actions = Actions(self.ws)
        self.actions.set_mode("email", "approve_each_action")
        self.ex = Executor(self.actions)
        self.token = self.ex.acquire("w", seconds=3600)["token"]
        self.sent_a = self.send(self.job_a, "thread-a")
        self.sent_b = self.send(self.job_b, "thread-b")
        self.sync = MailSync(self.ex)
        self.seq = 0

    def send(self, job, thread):
        envelope = self.actions.create_envelope("email", TO, FIRST, job_id=job)
        auth = self.actions.approve(envelope["envelope_id"], hours=24)["authorisation_id"]
        action = self.ex.reserve(self.token, auth, "email", TO, FIRST)["action_id"]
        self.ex.record(self.token, action, "accepted", provider_ref=thread)
        return action

    def msg(self, subject, body, sender="talent@acme.example", thread=None, **extra):
        self.seq += 1
        return {"message_id": f"m{self.seq}", "thread_id": thread or f"t{self.seq}", "history_id": 100 + self.seq,
                "from": sender, "subject": subject, "body": body, "received_at": soon(), **extra}

    def event(self, message_id):
        return self.ws.db.execute("SELECT * FROM mail_events WHERE message_id=?", (message_id,)).fetchone()

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_t_syn_01_rejection_naming_role_b_attaches_to_b(self):
        m = self.msg("Your application", "Unfortunately we will not be moving forward with the Platform Engineer role at Acme.")
        report = self.sync.sync([m])
        row = self.event(m["message_id"])
        self.assertEqual((self.job_b, "rejection", "attached"), (row["job_id"], row["classification"], row["state"]))
        self.assertEqual(["company_role"], __import__("json").loads(row["signals"]))
        self.assertEqual(1, report["matched"])

    def test_t_syn_02_rejection_without_role_goes_to_review(self):
        m = self.msg("Your application", "Unfortunately we have decided to go with other candidates at Acme.")
        self.assertEqual(1, self.sync.sync([m])["review"])
        row = self.event(m["message_id"])
        self.assertIsNone(row["job_id"])
        queued = self.sync.review_queue()
        self.assertEqual({self.job_a, self.job_b}, {c["job_id"] for c in queued[0]["candidates"]})

    def test_t_syn_03_rerun_creates_no_duplicates(self):
        batch = [self.msg("Re: Application", "Thank you for applying.", thread="thread-a"),
                 self.msg("Interview", "Can we schedule a call about REQ-1001?")]
        self.sync.sync(batch)
        again = self.sync.sync(batch)
        self.assertEqual(2, again["duplicate"])
        self.assertEqual(2, self.ws.db.execute("SELECT count(*) FROM mail_events").fetchone()[0])

    def test_signal_order_thread_action_id_requisition(self):
        thread = self.msg("Re: Application", "Thanks, received your application.", thread="thread-a")
        quoted = self.msg("Re", "Interview next week?\n> X-JW-Action-Id: " + self.sent_b)
        req = self.msg("Update", "Please complete the coding challenge for REQ-1001.", sender="noreply@ats.example")
        self.sync.sync([thread, quoted, req])
        self.assertEqual((self.job_a, '["thread"]', self.sent_a),
                         tuple(self.event("m1")[k] for k in ("job_id", "signals", "attempt_id")))
        self.assertEqual((self.job_b, '["action_id"]'), (self.event("m2")["job_id"], self.event("m2")["signals"]))
        self.assertEqual((self.job_a, '["requisition"]', "assessment"),
                         tuple(self.event("m3")[k] for k in ("job_id", "signals", "classification")))

    def test_company_alone_never_defaults_to_latest_application(self):
        m = self.msg("Hello", "Interview invitation from Acme.")
        self.sync.sync([m])
        self.assertEqual("review", self.event(m["message_id"])["state"])

    def test_role_match_needs_contact_in_window(self):
        late = self.msg("News", "Unfortunately the Platform Engineer role at Acme is closed.")
        late["received_at"] = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
        self.sync.sync([late])
        self.assertEqual("review", self.event(late["message_id"])["state"])

    def test_reply_cancels_followups_and_auto_reply_does_not(self):
        fu = Followups(self.ex)
        followup = fu.schedule(self.sent_a)["followup_id"]
        self.sync.sync([self.msg("Automatic reply", "I am out of the office.", thread="thread-a")])
        self.assertEqual("scheduled", self.ws.store.one("followups", followup)["state"])
        self.sync.sync([self.msg("Re: Application", "Thank you for applying.", thread="thread-a")])
        row = self.ws.store.one("followups", followup)
        self.assertEqual(("cancelled", "reply"), (row["state"], row["reason"]))

    def test_opt_out_suppresses_sender_and_journals(self):
        self.sync.sync([self.msg("Re", "Please remove me from your list.", sender=TO, thread="thread-a")])
        self.assertTrue(suppressed(self.ws, TO))
        self.assertEqual(["opt_out"], [e["reason"] for e in journal(self.ws.store.root)])

    def test_bounce_suppresses_original_destination(self):
        self.sync.sync([self.msg("Delivery Status Notification (Failure)", "Address not found.",
                                 sender="mailer-daemon@googlemail.com", references=["thread-b"])])
        self.assertEqual("bounce", self.event("m1")["classification"])
        self.assertTrue(suppressed(self.ws, TO))
        self.assertEqual(["hard_bounce"], [e["reason"] for e in journal(self.ws.store.root)])

    def test_partial_fetch_keeps_checkpoint_at_last_processed(self):
        good = self.msg("Re", "Thank you for applying.", thread="thread-a")
        bad = self.msg("Re", "x")
        bad["received_at"] = "not a time"
        self.assertCode("invalid_time", self.sync.sync, [good, bad])
        self.assertEqual(0, self.sync.checkpoint())
        self.sync.sync([good])
        self.assertEqual(good["history_id"], self.sync.checkpoint())

    def test_not_job_related_is_remembered_per_sender(self):
        first = self.msg("Newsletter", "Acme weekly digest.", sender="news@acme.example")
        self.sync.sync([first])
        self.sync.dismiss(first["message_id"], not_job_related=True)
        later = self.msg("Newsletter", "Acme weekly digest again.", sender="NEWS@acme.example")
        self.assertEqual(1, self.sync.sync([later])["ignored"])
        self.assertEqual([], self.sync.review_queue())

    def test_assign_attaches_and_applies_reply_effects(self):
        fu = Followups(self.ex)
        followup = fu.schedule(self.sent_b)["followup_id"]
        m = self.msg("Your application", "Unfortunately we went with other candidates at Acme.")
        self.sync.sync([m])
        self.sync.assign(m["message_id"], self.job_b)
        self.assertEqual(("attached", self.job_b), tuple(self.event(m["message_id"])[k] for k in ("state", "job_id")))
        self.assertEqual("cancelled", self.ws.store.one("followups", followup)["state"])
        self.assertCode("not_in_review", self.sync.assign, m["message_id"], self.job_a)

    def test_only_hashes_and_bounded_excerpt_are_stored(self):
        body = "Unfortunately the Platform Engineer role at Acme is filled. " + "secret " * 200
        m = self.msg("Private subject line", body, sender="person@acme.example")
        self.sync.sync([m])
        row = self.event(m["message_id"])
        dump = "\n".join(self.ws.db.iterdump())
        self.assertNotIn("person@acme.example", dump)
        self.assertNotIn("Private subject line", dump)
        self.assertLessEqual(len(row["excerpt"]), 200)
        self.assertEqual("acme.example", row["sender_domain"])

    def test_sent_folder_reconcile_found_and_not_found(self):
        envelope = self.actions.create_envelope("email", TO, FIRST, job_id=self.job_a)
        auth = self.actions.approve(envelope["envelope_id"], hours=24)["authorisation_id"]
        action = self.ex.reserve(self.token, auth, "email", TO, FIRST)["action_id"]
        self.ex.record(self.token, action, "unknown")
        other = [{"message_id": "s1", "headers": {"X-JW-Action-Id": "act_other"}}]
        self.assertEqual("send_unknown", self.sync.reconcile_sent(self.token, action, other)["state"])
        found = [{"message_id": "s2", "thread_id": "thread-x", "headers": {"X-JW-Action-Id": action}}]
        self.assertEqual("sent_accepted", self.sync.reconcile_sent(self.token, action, found)["state"])
        self.assertEqual("thread-x", self.ws.store.one("attempts", action)["provider_ref"])

    def test_classifier_order(self):
        self.assertEqual("rejection", classify("a@b.c", "Interview update", "Unfortunately no interview."))
        self.assertEqual("offer", classify("a@b.c", "Offer", "We are pleased to offer you the role."))
        self.assertEqual("other", classify("a@b.c", "Hi", "Lunch?"))

    def test_invalid_messages_fail_closed(self):
        self.assertCode("invalid_schema", self.sync.sync, [{"message_id": "x"}])
        bad = self.msg("s", "b")
        bad["extra"] = 1
        self.assertCode("invalid_schema", self.sync.sync, [bad])


if __name__ == "__main__":
    unittest.main()
