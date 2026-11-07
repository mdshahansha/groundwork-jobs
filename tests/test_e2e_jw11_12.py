"""E2E JW-11 and JW-12: approval, single-use claim, crash after reserve becomes unknown, and
reconciliation, each step in its own process (no CLI surface for actions exists yet)."""

import unittest

from e2e_support import E2E

SETUP = """
from jw.actions import Actions
actions = Actions(ws)
actions.set_mode("email", "approve_each_action")
email = {"subject": "Role", "body": "Hello."}
env = actions.create_envelope("email", "r@example.invalid", email, [b"%PDF cv"])
auth = actions.approve(env["envelope_id"])["authorisation_id"]
print(json.dumps({"auth": auth}))
"""
RESERVE = """
from jw.actions import Actions
from jw.execution import Executor
ex = Executor(Actions(ws))
token = ex.acquire("worker-a", seconds=1)["token"]
email = {"subject": "Role", "body": "Hello."}
print(json.dumps(ex.reserve(token, values["auth"], "email", "r@example.invalid", email, [b"%PDF cv"])))
"""


class ActionsE2E(E2E):
    def setUp(self):
        super().setUp()
        self.profile()

    def test_t_aut_01_edited_attachment_refused_in_a_later_process(self):
        auth = self.py(SETUP)["auth"]
        result = self.py("""
from jw.actions import Actions
from jw.contracts import WorkspaceError
try:
    Actions(ws).claim(values["auth"], "email", "r@example.invalid", {"subject": "Role", "body": "Hello."}, [b"%PDF edited"])
    print(json.dumps({"code": None}))
except WorkspaceError as exc:
    print(json.dumps({"code": exc.code, "state": ws.store.one("authorisations", values["auth"])["state"]}))
""", auth=auth)
        self.assertEqual({"code": "auth_hash_mismatch", "state": "invalid"}, result)

    def test_j8_process_dies_after_reserve_then_recovers_without_resend(self):
        auth = self.py(SETUP)["auth"]
        action = self.py(RESERVE, auth=auth)["action_id"]
        import time
        time.sleep(1.2)
        resumed = self.ok("resume", {"holder": "worker-b"})
        self.assertEqual(("reconcile_required", [action]), (resumed["state"], resumed["unresolved"]))
        done = self.py("""
from jw.actions import Actions
from jw.execution import Executor
from jw.contracts import WorkspaceError
ex = Executor(Actions(ws))
token = ws.db.execute("SELECT token FROM leases").fetchone()[0]
try:
    ex.reserve(token, values["auth"], "email", "r@example.invalid", {"subject": "Role", "body": "Hello."}, [b"%PDF cv"])
except WorkspaceError as exc:
    resend = exc.code
print(json.dumps({"resend": resend, "after": ex.reconcile(token, values["action"], "found", provider_ref="msg-1")}))
""", auth=auth, action=action)
        self.assertEqual(("unresolved_unknown", "sent_accepted"), (done["resend"], done["after"]["state"]))
        self.assertEqual("ready", self.ok("resume", {"holder": "worker-b"})["state"])


if __name__ == "__main__":
    unittest.main()
