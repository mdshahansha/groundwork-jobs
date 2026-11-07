"""JW-20: pause/resume order, durable checkpoint, reducer, and a crash matrix: a process death at
each write boundary leaves canonical state either fully before or fully after the step."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jw.actions import Actions
from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.execution import Executor
from jw.runs import Runs, reduce_application
from jw.tasks import Tasks
from jw.workspace import Workspace

TEXT = "Built Python services in 2021."
EMAIL = {"subject": "Platform Engineer application", "body": "Hello."}
TO = "recruiter@example.invalid"


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so no handler can swallow it."""


def later(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.open(create=True)
        self.source = self.ws.import_source(TEXT.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(TEXT))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Platform Engineer", "description": "S.",
                                    "requirements": ["Python"]})["job_id"]
        self.actions.set_mode("email", "approve_each_action")

    def open(self, create=False):
        self.ws = Workspace(self.root, create=create)
        self.addCleanup(self.ws.close)
        self.actions = Actions(self.ws)
        self.ex = Executor(self.actions)
        self.runs = Runs(self.ex)

    def reopen(self):
        self.ws.close()
        self.open()

    def auth(self):
        envelope = self.actions.create_envelope("email", TO, EMAIL, job_id=self.job)
        return self.actions.approve(envelope["envelope_id"])["authorisation_id"]

    def dump(self):
        db = sqlite3.connect(self.root / "workspace.sqlite3")
        try:
            return [line for line in db.iterdump()]
        finally:
            db.close()

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def draft(self):
        tasks = Tasks(self.ws)
        task = tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        return tasks, task

    def test_pause_stops_reservations_and_checkpoints(self):
        token = self.ex.acquire("w")["token"]
        auth = self.auth()
        progress = self.runs.pause()
        self.assertEqual((True, "resume"), (progress["stopped"], progress["next_safe_step"]))
        self.assertTrue((self.root / "progress.json").is_file())
        self.assertCode("stopped", self.ex.reserve, token, auth, "email", TO, EMAIL)

    def test_resume_order_reconcile_before_pending(self):
        tasks, task = self.draft()
        token = self.ex.acquire("w", seconds=10)["token"]
        action = self.ex.reserve(token, self.auth(), "email", TO, EMAIL)["action_id"]
        self.runs.pause()
        with patch("jw.execution.utcnow", return_value=later(60)):
            resumed = self.runs.resume("w2")
            self.assertEqual(("reconcile_required", [action], [action], []),
                             (resumed["state"], resumed["became_unknown"], resumed["unresolved"], resumed["pending"]))
            self.assertEqual("reconcile " + action, resumed["next_safe_step"])
            self.assertFalse(self.actions.stopped())
            self.ex.reconcile(resumed["token"], action, "found", provider_ref="msg-1")
            again = self.runs.resume("w2")
        self.assertEqual(("ready", [task]), (again["state"], again["pending"]))

    def test_resume_reports_version_change_and_expires_authorisations(self):
        self.runs.checkpoint()
        auth = self.auth()
        self.ws.pin_model("model-a")
        with patch("jw.runs.utcnow", return_value=later(25 * 3600)):
            resumed = self.runs.resume("w")
        self.assertEqual((["model"], [auth]), (resumed["versions_changed"], resumed["authorisations_expired"]))
        self.assertEqual("expired", self.ws.store.one("authorisations", auth)["state"])

    def test_second_worker_cannot_resume_while_lease_is_held(self):
        self.runs.resume("w1")
        self.assertCode("lease_held", self.runs.resume, "w2")

    def test_reducer_keeps_preparation_channel_and_outcome_separate(self):
        state = reduce_application(self.ws, self.job)
        self.assertEqual(("not_started", {"email": "not_attempted", "comment": "inactive", "ats": "inactive"}, None),
                         (state["preparation"], state["channels"], state["outcome"]))
        tasks, task = self.draft()
        self.assertEqual("drafting", reduce_application(self.ws, self.job)["preparation"])
        tasks.submit(task, canonical({"output": {"assertions": [{"text": TEXT, "claim_id": self.claim}]},
                     "usage": {"model": "fixture", "input_tokens": None, "output_tokens": None}}).encode())
        self.assertEqual("drafted", reduce_application(self.ws, self.job)["preparation"])
        tasks.verify_draft(task)
        token = self.ex.acquire("w")["token"]
        action = self.ex.reserve(token, self.auth(), "email", TO, EMAIL)["action_id"]
        self.assertEqual("sending", reduce_application(self.ws, self.job)["channels"]["email"])
        self.ex.record(token, action, "accepted", provider_ref="msg-1")
        self.ws.record_outcome(self.job, "interview", "2026-11-01T09:00:00+00:00")
        state = reduce_application(self.ws, self.job)
        self.assertEqual(("mechanically_verified", "sent_accepted", "interview"),
                         (state["preparation"], state["channels"]["email"], state["outcome"]["kind"]))
        other = self.ws.add_job({"company": "B", "title": "C", "description": "D", "requirements": []})["job_id"]
        self.assertEqual("not_attempted", reduce_application(self.ws, other)["channels"]["email"])

    def test_crash_matrix(self):
        """Kill the process at the audit write inside each step: nothing of the step survives."""
        token = self.ex.acquire("w")["token"]
        live = self.ex.reserve(token, self.auth(), "email", TO, EMAIL)["action_id"]
        auth = self.auth()
        steps = {
            "reserve": lambda: self.ex.reserve(token, auth, "email", TO, EMAIL),
            "record": lambda: self.ex.record(token, live, "accepted", provider_ref="msg-1"),
            "approve": lambda: self.actions.approve(self.actions.create_envelope("email", TO, EMAIL)["envelope_id"]),
            "revoke": lambda: self.actions.revoke(auth),
            "delete_source": lambda: self.ws.delete_source(self.source),
            "outcome": lambda: self.ws.record_outcome(self.job, "rejected", "2026-11-02T00:00:00+00:00"),
            "pin_model": lambda: self.ws.pin_model("model-z"),
            "stop": lambda: self.actions.stop(),
            "acquire": lambda: self.ex.acquire("w"),
        }
        for name, step in steps.items():
            with self.subTest(step=name):
                before = self.dump()
                original = self.ws.store.audit

                def die(kind, identifier):
                    original(kind, identifier)
                    raise Killed()

                with patch.object(self.ws.store, "audit", side_effect=die):
                    with self.assertRaises(Killed):
                        step()
                self.reopen()
                self.assertEqual(before, self.dump())

    def test_crash_during_checkpoint_keeps_previous_file(self):
        first = self.runs.checkpoint()
        with patch("jw.runs.os.replace", side_effect=Killed()):
            with self.assertRaises(Killed):
                self.runs.pause()
        self.assertEqual(first["at"], json.loads((self.root / "progress.json").read_text(encoding="utf-8"))["at"])

    def test_cli_pause_resume_state(self):
        self.ws.close()

        def run(command, payload):
            request = Path(self.temp.name) / (command + ".json")
            request.write_text(canonical(payload), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--workspace", str(self.root), command, "--input", str(request)])
            return code, json.loads(output.getvalue())["result"]

        self.assertTrue(run("pause", {})[1]["paused"])
        self.assertEqual("ready", run("resume", {"holder": "cli"})[1]["state"])
        self.assertEqual("not_started", run("application-state", {"job_id": self.job})[1]["preparation"])
        self.open()


if __name__ == "__main__":
    unittest.main()
