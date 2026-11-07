"""JW-02: Distilly host-inference output contract. The fixture profile was produced by a host agent
(Claude Code) following the pinned upstream owner prompts on synthetic source material. The pinned
writer's save step is exercised separately by tools/probe_distilly_profile.py."""

from pathlib import Path
import tempfile
import unittest

from jw.contracts import WorkspaceError
from jw.integrations import check_host_profile, map_profile
from jw.workspace import Workspace

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "distilly_host"
INJECTION = "Managed 50 people"


class DistillyHostTests(unittest.TestCase):
    def setUp(self):
        self.profile = (FIXTURES / "profile.md").read_text(encoding="utf-8")
        self.source = (FIXTURES / "source.md").read_bytes()

    def claims(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        ws = Workspace(Path(temp.name) / "ws", create=True)
        self.addCleanup(ws.close)
        source_id = ws.import_source(self.source, sensitivity="public")["source_id"]
        evidence, offset = [], 0
        for line in self.source.decode("utf-8").splitlines(keepends=True):
            body = line.strip()
            if body and "Ignore previous" not in body and not body.startswith("Synthetic candidate"):
                start = offset + line.index(body)
                evidence.append({"text": body, "claim_id": ws.add_claim(source_id, start, start + len(body))["claim_id"]})
            offset += len(line)
        return evidence

    def test_host_profile_meets_builder_contract(self):
        report = check_host_profile(self.profile)
        self.assertLessEqual(report["summary_chars"], 3000)
        self.assertGreaterEqual(report["inferred_lines"], 1)

    def test_supported_lines_map_to_claims_and_injection_never_does(self):
        result = map_profile(self.profile, self.claims())
        texts = {a["text"] for a in result["assertions"]}
        self.assertEqual({"Built Python services in 2021.", "Led the billing migration to PostgreSQL in 2023.",
                          "Prefers concise written updates over calls."}, texts)
        self.assertFalse(any(INJECTION in t for t in texts))
        self.assertGreater(result["unassessed_lines"], 0)
        self.assertEqual((False, False), (result["ready"], result["instructions_executed"]))

    def test_contract_rejects_missing_summary_persona_and_oversize(self):
        for bad in (self.profile.replace("## Always-on summary", "## Summary"),
                    self.profile.replace("- Name / how to address", "- You are Synthetic Candidate. Name"),
                    self.profile.replace("- Rhythm", "- " + "x" * 3100) if "- Rhythm" in self.profile else
                    self.profile.replace("## Work and projects", "- " + "x" * 3100 + "\n\n## Work and projects")):
            with self.assertRaises(WorkspaceError) as caught:
                check_host_profile(bad)
            self.assertEqual("distilly_contract", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
