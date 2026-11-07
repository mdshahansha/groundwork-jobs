"""E2E JW-14 and JW-17: mail sync and Sent-folder reconcile across processes; the loopback API
served by a separate process and called over real HTTP."""

from datetime import datetime, timedelta, timezone
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from e2e_support import E2E
from jw.api import csrf

SEND = """
from jw.actions import Actions
from jw.execution import Executor
actions = Actions(ws)
actions.set_mode("email", "approve_each_action")
email = {"subject": "Platform Engineer application", "body": "Hello."}
env = actions.create_envelope("email", "talent@acme.example", email, job_id=values["job"])
auth = actions.approve(env["envelope_id"])["authorisation_id"]
ex = Executor(actions)
token = ex.acquire("w")["token"]
action = ex.reserve(token, auth, "email", "talent@acme.example", email)["action_id"]
ex.record(token, action, values["outcome"], provider_ref="msg-1" if values["outcome"] == "accepted" else None)
ex.release(token)
print(json.dumps({"action": action}))
"""


def soon(minutes=5):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class MailAndApiE2E(E2E):
    def test_reply_matches_by_action_id_and_opt_out_suppresses(self):
        self.profile()
        job = self.job(company="Acme")
        action = self.py(SEND, job=job, outcome="accepted")["action"]
        result = self.py("""
from jw.actions import Actions
from jw.execution import Executor
from jw.mailsync import MailSync
from jw.suppression import suppressed
sync = MailSync(Executor(Actions(ws)))
messages = [
  {"message_id": "m1", "thread_id": "t1", "history_id": 101, "from": "talent@acme.example",
   "subject": "Re: Platform Engineer application", "received_at": values["at"],
   "body": "Thanks, we'd like to invite you to an interview. > X-JW-Action-Id: " + values["action"]},
  {"message_id": "m2", "thread_id": "t2", "history_id": 102, "from": "talent@acme.example",
   "subject": "Re: application", "received_at": values["at"], "body": "Please remove me from your list. > X-JW-Action-Id: " + values["action"]}]
sync.sync(messages)
again = sync.sync(messages)
rows = {r["message_id"]: (r["state"], r["job_id"]) for r in ws.db.execute("SELECT * FROM mail_events")}
print(json.dumps({"rows": rows, "suppressed": suppressed(ws, "talent@acme.example"), "again": again}))
""", action=action, at=soon())
        self.assertEqual(["attached", job], result["rows"]["m1"])
        self.assertTrue(result["suppressed"])
        self.assertEqual(2, len(result["rows"]))

    def test_unknown_send_resolved_only_by_sent_folder_evidence(self):
        self.profile()
        job = self.job(company="Acme")
        action = self.py(SEND, job=job, outcome="unknown")["action"]
        result = self.py("""
from jw.actions import Actions
from jw.execution import Executor
from jw.mailsync import MailSync
ex = Executor(Actions(ws))
token = ex.acquire("w2")["token"]
sync = MailSync(ex)
nothing = sync.reconcile_sent(token, values["action"], [])
found = sync.reconcile_sent(token, values["action"], [{"message_id": "sent-9", "headers": {"X-JW-Action-Id": values["action"]}}])
print(json.dumps({"nothing": nothing, "found": found}))
""", action=action)
        self.assertEqual("send_unknown", result["nothing"]["state"])
        self.assertEqual("sent_accepted", result["found"]["state"])

    def test_api_served_by_another_process(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = subprocess.Popen([sys.executable, "-c", "import sys; from jw.api import serve; "
                                   "serve(sys.argv[1], int(sys.argv[2])).serve_forever()", str(self.root), str(port)],
                                  env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        token_path = self.root / "api-token"
        for _ in range(100):
            if token_path.is_file():
                try:
                    socket.create_connection(("127.0.0.1", port), 0.2).close()
                    break
                except OSError:
                    pass
            time.sleep(0.05)
        token = token_path.read_text(encoding="utf-8").strip()
        base = f"http://127.0.0.1:{port}"

        def call(path, body=None, **headers):
            data = json.dumps(body).encode() if body is not None else None
            request = urllib.request.Request(base + path, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                try:
                    return exc.code, json.loads(exc.read())
                finally:
                    exc.close()

        auth = {"Authorization": "Bearer " + token}
        self.assertEqual(200, call("/status", **auth)[0])
        self.assertEqual(401, call("/status")[0])
        self.assertEqual(403, call("/status", Origin="https://evil.example", **auth)[0])
        job = {"command": "job-add", "input": {"company": "A", "title": "B", "description": "C", "requirements": []}}
        self.assertEqual(403, call("/command", job, **{"Content-Type": "application/json"}, **auth)[0])
        status, body = call("/command", job, **{"Content-Type": "application/json", "X-JW-CSRF": csrf(token)}, **auth)
        self.assertEqual((200, True), (status, body["ok"]))
        self.assertEqual(501, call("/command", {"command": "send"}, **{"Content-Type": "application/json",
                                                                       "X-JW-CSRF": csrf(token)}, **auth)[0])


if __name__ == "__main__":
    unittest.main()
