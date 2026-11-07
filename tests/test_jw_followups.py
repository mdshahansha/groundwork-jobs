"""JW-15: follow-up scheduling and the approval / cancellation / suppression race contracts."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.followups import Followups
from jw.suppression import suppress
from jw.workspace import Workspace

TO = "recruiter@example.invalid"
FIRST = {"subject": "Application", "body": "Hello."}
NUDGE = {"subject": "Following up", "body": "Checking in."}


def days(n):
    return (datetime.now(timezone.utc) + timedelta(days=n)).isoformat()


class FollowupTests(unittest.TestCase):
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
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "T", "description": "D",
                                    "requirements": []})["job_id"]
        self.actions = Actions(self.ws)
        self.actions.set_mode("email", "approve_each_action")
        self.ex = Executor(self.actions)
        self.fu = Followups(self.ex)
        self.token = self.ex.acquire("w", seconds=3600)["token"]
        action = self.ex.reserve(self.token, self.auth(FIRST), "email", TO, FIRST)["action_id"]
        self.ex.record(self.token, action, "accepted", provider_ref="msg-1")
        self.followup = self.fu.schedule(action)
        self.action = action

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def auth(self, content):
        envelope = self.actions.create_envelope("email", TO, content, job_id=self.job)
        return self.actions.approve(envelope["envelope_id"], hours=24 * 14)["authorisation_id"]

    def reserve_at(self, at, auth=None):
        auth = auth or self.auth(NUDGE)
        with patch("jw.followups.utcnow", return_value=at), patch("jw.execution.utcnow", return_value=at), \
                patch("jw.actions.utcnow", return_value=at):
            token = self.ex.acquire("w", seconds=3600)["token"]
            self.later_token = token
            return auth, self.fu.reserve(token, self.followup["followup_id"], auth, NUDGE)

    def test_scheduled_seven_days_after_acceptance_and_limited(self):
        self.assertEqual((1, "scheduled"), (self.followup["seq"], self.followup["state"]))
        self.assertCode("followup_limit", self.fu.schedule, self.action)
        self.assertEqual([], self.fu.due()["due"])
        self.assertEqual(1, len(self.fu.due(days(8))["due"]))

    def test_not_due_is_refused_and_approval_unspent(self):
        auth = self.auth(NUDGE)
        self.assertCode("followup_not_due", self.fu.reserve, self.token, self.followup["followup_id"], auth, NUDGE)
        self.assertEqual("active", self.ws.store.one("authorisations", auth)["state"])

    def test_due_follow_up_is_reserved_once(self):
        auth, reserved = self.reserve_at(days(8))
        self.assertEqual("sending", reserved["state"])
        self.assertEqual("reserved", self.ws.store.one("followups", self.followup["followup_id"])["state"])
        with patch("jw.followups.utcnow", return_value=days(8)), patch("jw.execution.utcnow", return_value=days(8)):
            token = self.later_token
            self.ex.record(token, reserved["action_id"], "accepted", provider_ref="msg-2")
            self.assertCode("followup_already_sending", self.fu.reserve, token, self.followup["followup_id"],
                            self.auth(NUDGE), NUDGE)

    def test_cancel_before_reserve_wins(self):
        self.fu.cancel(self.followup["followup_id"], "reply")
        auth = self.auth(NUDGE)
        with self.assertRaises(WorkspaceError) as caught:
            self.reserve_at(days(8), auth)
        self.assertEqual("followup_cancelled", caught.exception.code)
        self.assertEqual("active", self.ws.store.one("authorisations", auth)["state"])

    def test_reserve_before_cancel_wins(self):
        self.reserve_at(days(8))
        self.assertCode("followup_already_sending", self.fu.cancel, self.followup["followup_id"], "reply")

    def test_outcome_recorded_after_scheduling_cancels(self):
        self.ws.record_outcome(self.job, "rejected", datetime.now(timezone.utc).isoformat())
        with self.assertRaises(WorkspaceError) as caught:
            self.reserve_at(days(8))
        self.assertEqual("followup_cancelled", caught.exception.code)
        self.assertEqual("outcome_change", self.ws.store.one("followups", self.followup["followup_id"])["reason"])

    def test_suppression_after_scheduling_cancels(self):
        suppress(self.ws, TO, "opt_out")
        self.assertEqual([{"followup_id": self.followup["followup_id"], "reason": "suppressed"}],
                         self.fu.due(days(8))["cancelled"])

    def test_cancel_is_idempotent_and_validated(self):
        self.fu.cancel(self.followup["followup_id"], "candidate_request")
        self.assertEqual("candidate_request", self.fu.cancel(self.followup["followup_id"], "reply")["reason"])
        self.assertCode("invalid_schema", self.fu.cancel, self.followup["followup_id"], "bored")


if __name__ == "__main__":
    unittest.main()
