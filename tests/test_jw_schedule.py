"""JW-23: caps in the candidate's zone, allowed hours across DST, waiting slots, partial dates (FR-AUT-06)."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.execution import Executor
from jw.schedule import Schedule, partial_date
from jw.workspace import Workspace

EMAIL = {"subject": "Role", "body": "Hello."}
TO = "r@example.invalid"


def policy(zone="America/New_York", cap=2, hours=(9, 17)):
    return {"timezone": zone, "channels": {"email": {"daily_cap": cap, "hours": list(hours)}}}


class ScheduleTests(unittest.TestCase):
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
        self.schedule = Schedule(self.ws)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def reserve_at(self, at):
        auth = self.actions.approve(self.actions.create_envelope("email", TO, EMAIL)["envelope_id"])["authorisation_id"]
        with patch("jw.schedule.utcnow", return_value=at), patch("jw.execution.utcnow", return_value=at):
            if not hasattr(self, "token"):
                self.token = self.ex.acquire("w", seconds=3600)["token"]
            return self.ex.reserve(self.token, auth, "email", TO, EMAIL)

    def test_policy_bounds(self):
        self.assertCode("cap_above_hard_limit", self.schedule.set_policy, policy(cap=26))
        self.assertCode("invalid_schema", self.schedule.set_policy, policy(zone="Mars/Olympus"))
        self.assertCode("invalid_schema", self.schedule.set_policy, policy(hours=(17, 9)))
        self.assertCode("invalid_schema", self.schedule.set_policy, {"timezone": "UTC", "channels": {"sms": {}}})

    def test_outside_hours_waits_with_next_local_slot(self):
        self.schedule.set_policy(policy())
        # 2026-11-09 06:00 New York (EST, UTC-5) is before 09:00.
        waiting = self.schedule.check("email", "2026-11-09T11:00:00+00:00")
        self.assertEqual(("outside_allowed_hours", "2026-11-09T14:00:00+00:00"), (waiting[0], waiting[2]))
        self.assertIsNone(self.schedule.check("email", "2026-11-09T15:00:00+00:00"))
        evening = self.schedule.check("email", "2026-11-09T23:00:00+00:00")
        self.assertEqual("2026-11-10T14:00:00+00:00", evening[2])

    def test_reserve_refuses_outside_hours(self):
        self.schedule.set_policy(policy())
        self.assertCode("outside_allowed_hours", self.reserve_at, "2026-11-09T03:00:00+00:00")

    def test_cap_counts_local_day_and_resets_at_local_midnight(self):
        self.schedule.set_policy(policy(cap=2, hours=(0, 24)))
        # 23:30 and 23:45 New York on 9 Nov are already 10 Nov in UTC: still one local day.
        self.reserve_at("2026-11-10T04:30:00+00:00")
        self.reserve_at("2026-11-10T04:45:00+00:00")
        waiting = self.schedule.check("email", "2026-11-10T04:50:00+00:00")
        self.assertEqual(("daily_cap_reached", "2026-11-10T05:00:00+00:00"), (waiting[0], waiting[2]))
        self.assertIsNone(self.schedule.check("email", "2026-11-10T05:00:00+00:00"))

    def test_unknown_attempts_count_against_cap(self):
        self.schedule.set_policy(policy(cap=1, hours=(0, 24)))
        action = self.reserve_at("2026-11-09T15:00:00+00:00")["action_id"]
        with patch("jw.execution.utcnow", return_value="2026-11-09T15:01:00+00:00"):
            self.ex.record(self.token, action, "unknown")
        self.assertEqual("daily_cap_reached", self.schedule.check("email", "2026-11-09T16:00:00+00:00")[0])

    def test_dst_spring_gap_and_fall_overlap(self):
        # 2026-03-08: New York clocks jump 02:00 -> 03:00. A 02:00 window start moves to 03:00 EDT.
        self.schedule.set_policy(policy(hours=(2, 5)))
        self.assertEqual("2026-03-08T07:00:00+00:00", self.schedule.check("email", "2026-03-08T05:00:00+00:00")[2])
        # 2026-11-01: 01:00 happens twice; the window opens at the first one (EDT, UTC-4).
        self.schedule.set_policy(policy(hours=(1, 5)))
        self.assertEqual("2026-11-01T05:00:00+00:00", self.schedule.check("email", "2026-11-01T03:00:00+00:00")[2])

    def test_cap_zero_never_sends(self):
        self.schedule.set_policy(policy(cap=0))
        self.assertCode("channel_capped_off", self.schedule.check, "email", "2026-11-09T15:00:00+00:00")

    def test_partial_dates_keep_precision(self):
        self.assertEqual(("year", "2026-01-01", "2026-12-31", "2026"),
                         tuple(partial_date("2026")[k] for k in ("precision", "start", "end", "display")))
        self.assertEqual(("month", "2028-02-29", "Feb 2028"),
                         tuple(partial_date("2028-02")[k] for k in ("precision", "end", "display")))
        self.assertEqual("4 Sep 2026", partial_date("2026-09-04")["display"])
        for bad in ("2026-13", "2026-02-30", "Sept 2026", "26"):
            with self.subTest(bad=bad):
                self.assertCode("invalid_date", partial_date, bad)


if __name__ == "__main__":
    unittest.main()
