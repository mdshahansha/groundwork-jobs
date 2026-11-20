"""JW-16: --dry-run effect matrix (FR-SIM-01). Every simulated command leaves the workspace
byte-for-byte equal in content, writes no requested file and reports what it would change."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from jw.actions import Actions
from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.execution import Executor
from jw.gmail import DemoGmail, GmailAdapter
from jw.simulation import ACTIVE, run
from jw.tasks import Tasks
from jw.workspace import Workspace
from test_jw_ranking import assessment, policy

TEXT = "Built Python services in 2021."


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        ws = Workspace(self.root, create=True)
        self.source = ws.import_source(TEXT.encode(), sensitivity="public")["source_id"]
        self.claim = ws.add_claim(self.source, 0, len(TEXT))["claim_id"]
        ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        ws.publish_profile()
        ws.set_policy(policy())
        self.job = ws.add_job({"company": "Fixture Co", "title": "Platform Engineer", "description": "Synthetic.",
                               "requirements": ["Python"]})["job_id"]
        tasks = Tasks(ws)
        self.task = tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        tasks.submit(self.task, canonical({"output": {"assertions": [{"text": TEXT, "claim_id": self.claim}]},
                     "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}).encode())
        ws.close()

    def snapshot(self):
        db = sqlite3.connect(self.root / "workspace.sqlite3")
        try:
            return "\n".join(db.iterdump())
        finally:
            db.close()

    def dry(self, command, payload=None, *extra):
        args = ["--workspace", str(self.root), command, "--dry-run", *extra]
        if payload is not None:
            request = Path(self.temp.name) / (command + ".json")
            request.write_bytes(payload if isinstance(payload, bytes) else canonical(payload).encode())
            args += ["--input", str(request)]
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_effect_matrix_leaves_workspace_unchanged(self):
        out_pdf = Path(self.temp.name) / "letter.pdf"
        mapping = [{"index": 0, "state": "supported", "claim_id": self.claim}]
        cases = [
            ("source-import", "Ran observability reviews.".encode(), {"sources": 1}, ["--sensitivity", "public"]),
            ("job-add", {"company": "B", "title": "C", "description": "D", "requirements": []}, {"jobs": 1}, []),
            ("rank", {"job_id": self.job, "mapping": mapping, "assessment": assessment()}, {"rankings": 1}, []),
            ("task-create", {"job_id": self.job, "kind": "draft_cv", "consent": True}, {"tasks": 1}, []),
            ("draft-verify", {"task_id": self.task}, {"verifications": 1}, []),
            ("source-delete", {"source_id": self.source, "confirm": True}, {"deletions": 1}, []),
            ("model-pin", {"model": "model-a"}, {"controls": 1}, []),
            ("draft-render", {"task_id": self.task, "output_path": str(out_pdf)}, None, []),
        ]
        for command, payload, rows, extra in cases:
            with self.subTest(command=command):
                before = self.snapshot()
                code, out = self.dry(command, payload, *extra)
                self.assertEqual(0, code, out)
                result = out["result"]
                self.assertTrue(result["simulated"])
                self.assertEqual([], result["effects"]["external_actions"])
                if rows:
                    for table, delta in rows.items():
                        self.assertEqual(delta, result["effects"]["rows"].get(table), result["effects"])
                self.assertEqual(before, self.snapshot())
        self.assertFalse(out_pdf.exists())
        self.assertEqual([str(out_pdf)], result["effects"]["files"])

    def test_refusals_still_refuse_under_dry_run(self):
        code, out = self.dry("source-delete", {"source_id": self.source, "confirm": False})
        self.assertEqual((2, "confirmation_required"), (code, out["error"]["code"]))

    def test_simulated_action_does_not_consume_authorisation(self):
        ws = Workspace(self.root)
        self.addCleanup(ws.close)
        actions = Actions(ws)
        email = {"subject": "Role", "body": "Hello."}
        actions.set_mode("email", "approve_each_action")
        auth = actions.approve(actions.create_envelope("email", "r@example.invalid", email)["envelope_id"])
        auth = auth["authorisation_id"]
        sim = actions.simulate(auth, "email", "r@example.invalid", email)
        self.assertEqual((True, True, []), (sim["simulated"], sim["would_send"], sim["refusals"]))
        self.assertEqual(["auth_hash_mismatch"],
                         actions.simulate(auth, "email", "x@example.invalid", email)["refusals"])
        self.assertEqual("active", ws.store.one("authorisations", auth)["state"])
        self.assertEqual("used", actions.claim(auth, "email", "r@example.invalid", email)["state"])
        actions.stop()
        self.assertEqual({"stopped", "auth_used"},
                         set(actions.simulate(auth, "email", "r@example.invalid", email)["refusals"]))

    def test_provider_writes_are_refused_before_any_transport_is_built(self):
        resume = Path(self.temp.name) / "resume.pdf"
        resume.write_bytes(b"%PDF-1.4 synthetic")
        cases = [("lead-send", {"resume_path": str(resume)}),
                 ("mail-sync", {"transport": "http", "allowed": ["read", "label"]})]
        for command, payload in cases:
            with self.subTest(command=command), mock.patch("jw.gmail.transport") as transport:
                before = self.snapshot()
                code, out = self.dry(command, payload)
                self.assertEqual((2, "unsupported_capability"), (code, out["error"]["code"]))
                transport.assert_not_called()
                self.assertEqual(before, self.snapshot())

    def test_read_only_mail_sync_is_not_refused_under_dry_run(self):
        gmail = DemoGmail(scopes=("gmail.readonly",))
        gmail.deliver("news@other.example", "Weekly digest", "Nothing here.")
        before = self.snapshot()
        with mock.patch("jw.gmail.transport", return_value=gmail):
            code, out = self.dry("mail-sync", {"transport": "http", "allowed": ["read"]})
        self.assertEqual(0, code, out)
        self.assertEqual((True, 1), (out["result"]["simulated"], out["result"]["result"]["fetched"]))
        self.assertEqual(before, self.snapshot())

    def test_gmail_adapter_refuses_writes_inside_any_simulation(self):
        gmail = DemoGmail(scopes=("gmail.modify",))
        content = {"subject": "Role", "body": "Hello."}
        ws = Workspace(self.root)
        actions = Actions(ws)
        actions.set_mode("email", "approve_each_action")
        executor = Executor(actions)
        token = executor.acquire("w", seconds=3600)["token"]
        envelope = actions.create_envelope("email", "r@example.invalid", content, job_id=self.job)
        auth = actions.approve(envelope["envelope_id"], hours=24)["authorisation_id"]
        live = GmailAdapter(executor, gmail, allowed=("read", "label", "send"))
        live.sync()
        sent = live.send(token, auth, "r@example.invalid", content)
        thread = executor.attempt(sent["action_id"])["provider_ref"]
        gmail.deliver("r@example.invalid", "Re: Role", "Thank you for applying.", thread=thread)
        auth = actions.approve(actions.create_envelope("email", "s@example.invalid", content,
                                                       job_id=self.job)["envelope_id"], hours=24)
        ws.close()
        calls, labels = len(gmail.calls), dict(gmail.labels)

        def sync(ws, command, data):
            GmailAdapter(Executor(Actions(ws)), gmail, allowed=("read", "label")).sync()

        def send(ws, command, data):
            executor = Executor(Actions(ws))
            token = executor.acquire("w", seconds=3600)["token"]
            adapter = GmailAdapter(executor, gmail, allowed=("send",))
            adapter.send(token, auth["authorisation_id"], "s@example.invalid", content)

        for name, dispatch in (("label", sync), ("send", send)):
            with self.subTest(write=name), self.assertRaises(WorkspaceError) as refused:
                run(self.root, "probe", {}, dispatch)
            self.assertEqual("unsupported_capability", refused.exception.code)
            self.assertFalse(ACTIVE.get())
        self.assertFalse({"create_label", "modify", "send"} & set(gmail.calls[calls:]))
        self.assertEqual(labels, gmail.labels)
        ws = Workspace(self.root)
        self.addCleanup(ws.close)
        self.assertEqual("active", ws.store.one("authorisations", auth["authorisation_id"])["state"])

    def test_caller_paths_are_redirected_into_the_scratch_copy(self):
        backups = Path(self.temp.name) / "backups"
        code, out = self.dry("backup", {"to": str(backups)})
        self.assertEqual(0, code, out)
        self.assertEqual([str(backups)], out["result"]["effects"]["files"])
        self.assertFalse(backups.exists())
        export = Path(self.temp.name) / "leads.csv"
        code, out = self.dry("lead-filter", {"export_path": str(export)})
        self.assertEqual(0, code, out)
        self.assertEqual([str(export)], out["result"]["effects"]["files"])
        self.assertFalse(export.exists())

    def test_dry_run_does_not_migrate_an_older_live_database(self):
        db = sqlite3.connect(self.root / "workspace.sqlite3")
        db.execute("DROP TABLE lead_drafts")
        db.execute("PRAGMA user_version=16")
        db.commit()
        db.close()
        code, out = self.dry("status")
        self.assertEqual(0, code, out)
        db = sqlite3.connect(self.root / "workspace.sqlite3")
        self.addCleanup(db.close)
        self.assertEqual(16, db.execute("PRAGMA user_version").fetchone()[0])

    def test_non_object_input_is_a_schema_error(self):
        code, out = self.dry("rankings", [])
        self.assertEqual((2, "invalid_schema"), (code, out["error"]["code"]))

if __name__ == "__main__":
    unittest.main()
