"""JW-12: lease, fencing tokens, attempt reservation and uncertain-outcome recovery.
Provider faults are simulated by recording (or not recording) outcomes; nothing is sent."""

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.workspace import Workspace

EMAIL = {"subject": "Platform Engineer application", "body": "Hello, I am applying for the role."}
CV = b"%PDF-1.4 synthetic cv"
TO = "recruiter@example.invalid"


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class ExecutionTests(unittest.TestCase):
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
        self.actions = Actions(self.ws)
        self.actions.set_mode("email", "approve_each_action")
        self.ex = Executor(self.actions)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def auth(self):
        envelope = self.actions.create_envelope("email", TO, EMAIL, [CV])
        return self.actions.approve(envelope["envelope_id"])["authorisation_id"]

    def reserve(self, token, auth=None):
        return self.ex.reserve(token, auth or self.auth(), "email", TO, EMAIL, [CV])["action_id"]

    def test_happy_path_records_action_id_before_send_and_accepts(self):
        token = self.ex.acquire("worker-a")["token"]
        reserved = self.ex.reserve(token, self.auth(), "email", TO, EMAIL, [CV])
        self.assertEqual(("sending", reserved["action_id"]), (reserved["state"], reserved["headers"]["X-JW-Action-Id"]))
        self.assertEqual("in_flight", self.ws.store.one("attempts", reserved["action_id"])["state"])
        done = self.ex.record(token, reserved["action_id"], "accepted", provider_ref="msg-1")
        self.assertEqual("sent_accepted", done["state"])

    def test_reservation_spends_the_authorisation_once(self):
        token = self.ex.acquire("worker-a")["token"]
        auth = self.auth()
        self.reserve(token, auth)
        self.assertCode("auth_used", self.ex.reserve, token, auth, "email", TO, EMAIL, [CV])

    def test_second_worker_cannot_take_a_live_lease(self):
        self.ex.acquire("worker-a")
        self.assertCode("lease_held", self.ex.acquire, "worker-b")

    def test_two_workers_loser_writes_rejected_by_fencing_token(self):
        old = self.ex.acquire("worker-a", seconds=10)["token"]
        action = self.reserve(old)
        with patch("jw.execution.utcnow", return_value=later(60)):
            new = self.ex.acquire("worker-b")["token"]
            self.assertGreater(new, old)
            self.assertCode("lease_lost", self.ex.record, old, action, "accepted", provider_ref="msg-1")
            self.assertCode("lease_lost", self.ex.reserve, old, self.auth(), "email", TO, EMAIL, [CV])
            self.assertCode("lease_lost", self.ex.renew, old)

    def test_crash_after_accept_becomes_unknown_then_reconciles_without_resend(self):
        # J8: the provider accepted, the process died before the result was stored.
        old = self.ex.acquire("worker-a", seconds=10)["token"]
        action = self.reserve(old)
        with patch("jw.execution.utcnow", return_value=later(60)):
            recovered = self.ex.acquire("worker-a")
            self.assertEqual([action], recovered["unknown"])
            self.assertEqual("send_unknown", self.ex.attempt(action)["state"])
            token = recovered["token"]
            self.assertCode("unresolved_unknown", self.ex.reserve, token, self.auth(), "email", TO, EMAIL, [CV])
            done = self.ex.reconcile(token, action, "found", provider_ref="msg-1")
        self.assertEqual(("sent_accepted", "msg-1"), (done["state"], self.ex.attempt(action)["provider_ref"]))

    def test_timeout_is_unknown_and_not_found_is_not_failure(self):
        token = self.ex.acquire("worker-a")["token"]
        action = self.reserve(token)
        self.assertEqual("send_unknown", self.ex.record(token, action, "unknown")["state"])
        self.assertEqual("send_unknown", self.ex.reconcile(token, action, "not_found")["state"])
        self.assertCode("unresolved_unknown", self.ex.reserve, token, self.auth(), "email", TO, EMAIL, [CV])
        self.assertCode("invalid_schema", self.ex.reconcile, token, action, "rejected")
        self.assertEqual("send_failed", self.ex.reconcile(token, action, "rejected",
                                                          evidence="Provider bounce 550")["state"])
        self.reserve(token)

    def test_unknown_blocks_only_its_own_channel(self):
        token = self.ex.acquire("worker-a")["token"]
        self.ex.record(token, self.reserve(token), "unknown")
        self.actions.set_mode("comment", "approve_each_action")
        envelope = self.actions.create_envelope("comment", "https://posts.example.invalid/1", {"body": "Great post."})
        auth = self.actions.approve(envelope["envelope_id"])["authorisation_id"]
        reserved = self.ex.reserve(token, auth, "comment", "https://posts.example.invalid/1", {"body": "Great post."})
        self.assertEqual("publishing", reserved["state"])

    def test_outcomes_are_one_way(self):
        token = self.ex.acquire("worker-a")["token"]
        action = self.reserve(token)
        self.ex.record(token, action, "failed", evidence="Provider rejected: 400")
        self.assertCode("attempt_not_in_flight", self.ex.record, token, action, "accepted", provider_ref="x")
        self.assertCode("attempt_not_unknown", self.ex.reconcile, token, action, "found", provider_ref="x")
        self.assertCode("invalid_schema", self.ex.record, token, self.reserve(token), "accepted")

    def test_stop_flag_and_refused_reservation_record_nothing(self):
        token = self.ex.acquire("worker-a")["token"]
        auth = self.auth()
        self.actions.stop()
        self.assertCode("stopped", self.ex.reserve, token, auth, "email", TO, EMAIL, [CV])
        self.assertEqual(0, self.ws.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
        self.assertEqual("active", self.ws.store.one("authorisations", auth)["state"])

    def test_hash_mismatch_at_reservation_invalidates_and_records_nothing(self):
        token = self.ex.acquire("worker-a")["token"]
        auth = self.auth()
        self.assertCode("auth_hash_mismatch", self.ex.reserve, token, auth, "email", TO, EMAIL, [CV + b"x"])
        self.assertEqual("invalid", self.ws.store.one("authorisations", auth)["state"])
        self.assertEqual(0, self.ws.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])

    def test_release_lets_another_worker_in_and_old_token_is_dead(self):
        token = self.ex.acquire("worker-a")["token"]
        self.ex.release(token)
        self.assertGreater(self.ex.acquire("worker-b")["token"], token)
        self.assertCode("lease_lost", self.ex.release, token)

    def test_lease_bounds(self):
        for seconds in (0, 3601, 1.5):
            with self.subTest(seconds=seconds):
                self.assertCode("invalid_schema", self.ex.acquire, "worker-a", seconds=seconds)
        self.assertCode("lease_lost", self.ex.reserve, 1, self.auth(), "email", TO, EMAIL, [CV])


if __name__ == "__main__":
    unittest.main()
