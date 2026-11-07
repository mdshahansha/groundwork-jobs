"""End-to-end harness: every step runs the real `jw` CLI in a separate process against a real
workspace directory, the way a user or host agent would. Steps with no CLI surface yet run a
short Python driver in a separate process, so no state is shared with the test process."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

SRC = str(Path(__file__).resolve().parents[1] / "src")
CV = "Built Python services in 2021."


class E2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.root = self.dir / "workspace"
        self.env = dict(os.environ, PYTHONPATH=SRC)
        self.ok("init")

    def cli(self, command, payload=None, *flags, raw=None):
        args = [sys.executable, "-m", "jw.cli", "--workspace", str(self.root), command, *flags]
        if payload is not None or raw is not None:
            request = self.dir / f"req-{command}-{len(list(self.dir.glob('req-*')))}"
            request.write_bytes(raw if raw is not None else json.dumps(payload).encode("utf-8"))
            args += ["--input", str(request)]
        done = subprocess.run(args, capture_output=True, env=self.env, timeout=120, check=False)
        return done.returncode, json.loads(done.stdout.decode("utf-8"))

    def ok(self, command, payload=None, *flags, raw=None):
        code, out = self.cli(command, payload, *flags, raw=raw)
        self.assertEqual(0, code, out)
        return out["result"]

    def fails(self, code_name, command, payload=None, *flags, raw=None):
        code, out = self.cli(command, payload, *flags, raw=raw)
        self.assertNotEqual(0, code, out)
        self.assertEqual(code_name, out["error"]["code"], out)
        return out

    def py(self, body, **values):
        """Run a driver in a fresh interpreter. `ws`, `root` and `values` are predefined; it prints JSON."""
        script = "import json, sys\nfrom pathlib import Path\nfrom jw.workspace import Workspace\n" \
                 "root = Path(sys.argv[1]); values = json.loads(sys.argv[2]); ws = Workspace(root)\n" \
                 "try:\n" + textwrap.indent(textwrap.dedent(body), "    ") + "\nfinally:\n    ws.close()\n"
        done = subprocess.run([sys.executable, "-c", script, str(self.root), json.dumps(values)],
                              capture_output=True, env=self.env, timeout=120, check=False)
        self.assertEqual(0, done.returncode, done.stderr.decode("utf-8")[-2000:])
        return json.loads(done.stdout.decode("utf-8").strip().splitlines()[-1])

    def profile(self, text=CV, sensitivity="public"):
        source = self.ok("source-import", None, "--sensitivity", sensitivity, raw=text.encode())["source_id"]
        claim = self.ok("claim-add", {"source_id": source, "start": 0, "end": len(text)})["claim_id"]
        self.ok("profile-set", {"name": "Synthetic Candidate", "email": "candidate@example.invalid"})
        self.ok("profile-publish")
        return source, claim

    def job(self, **changes):
        data = {"company": "Fixture Co", "title": "Platform Engineer", "description": "Synthetic.",
                "requirements": ["Python"]}
        data.update(changes)
        return self.ok("job-add", data)["job_id"]

    def draft(self, job, claim, kind="draft_letter", text=CV):
        task = self.ok("task-create", {"job_id": job, "kind": kind, "consent": True})["task_id"]
        self.ok("task-submit", {"task_id": task, "response": {
            "output": {"assertions": [{"text": text, "claim_id": claim}]},
            "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}})
        return task
