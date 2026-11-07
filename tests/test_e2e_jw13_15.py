"""E2E JW-13 and JW-15: CLI suppression survives restore and cancels a scheduled follow-up."""

import unittest

from e2e_support import E2E

SENT = """
from jw.actions import Actions
from jw.execution import Executor
from jw.followups import Followups
actions = Actions(ws)
actions.set_mode("email", "approve_each_action")
email = {"subject": "Role", "body": "Hello."}
env = actions.create_envelope("email", "r@example.invalid", email, job_id=values["job"])
auth = actions.approve(env["envelope_id"])["authorisation_id"]
ex = Executor(actions)
token = ex.acquire("w")["token"]
action = ex.reserve(token, auth, "email", "r@example.invalid", email)["action_id"]
ex.record(token, action, "accepted", provider_ref="msg-1")
ex.release(token)
print(json.dumps(Followups(ex).schedule(action)))
"""


class SuppressionE2E(E2E):
    def test_suppression_survives_restore_and_cancels_follow_up(self):
        self.profile()
        job = self.job()
        followup = self.py(SENT, job=job)
        backup = self.ok("backup", {"to": str(self.dir / "backups")})["backup"]
        self.ok("suppress", {"address": "R@Example.invalid", "reason": "opt_out"})
        self.ok("restore", {"backup": backup, "confirm": True})
        self.ok("resume", {"holder": "w2"})
        result = self.py("""
from datetime import datetime, timedelta, timezone
from jw.actions import Actions
from jw.execution import Executor
from jw.followups import Followups
from jw.suppression import suppressed
later = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()
print(json.dumps({"suppressed": suppressed(ws, "r@example.invalid"),
                  "due": Followups(Executor(Actions(ws))).due(later)}))
""")
        self.assertTrue(result["suppressed"])
        self.assertEqual([{"followup_id": followup["followup_id"], "reason": "suppressed"}], result["due"]["cancelled"])
        self.fails("invalid_schema", "suppress", {"address": "x@example.invalid", "reason": "wrong_recipient"})


if __name__ == "__main__":
    unittest.main()
