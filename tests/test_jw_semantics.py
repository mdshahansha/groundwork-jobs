"""JW-05 paraphrase guard: labelled synthetic corpus plus approval lifecycle. Not entailment."""

from pathlib import Path
import json
import tempfile
import unittest

from jw.cli import dispatch
from jw.contracts import WorkspaceError, canonical
from jw.semantics import check
from jw.tasks import Tasks
from jw.workspace import Workspace

CLAIM = "Built Python services for 3 internal teams at Fixture Co."

# (claim, candidate wording, expected findings). Empty findings means the guard passes.
CORPUS = [
    (CLAIM, CLAIM, []),
    (CLAIM, "For 3 internal teams at Fixture Co, built Python services.", []),
    (CLAIM, "Built Python services for 3 teams at Fixture Co.", []),
    (CLAIM, "Built Python services for 4 internal teams at Fixture Co.", ["quantity_changed"]),
    (CLAIM, "Built Python services for internal teams at Fixture Co.", ["quantity_changed"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co and Acme.", ["entity_added", "new_content"]),
    (CLAIM, "Built Python and Go services for 3 internal teams at Fixture Co.", ["entity_added"]),
    (CLAIM, "Led Python services for 3 internal teams at Fixture Co.", ["scope_escalation"]),
    (CLAIM, "Built all Python services for 3 internal teams at Fixture Co.", ["scope_escalation"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co as a senior engineer.",
     ["scope_escalation", "new_content"]),
    (CLAIM, "Did not build Python services for 3 internal teams at Fixture Co.", ["negation_changed", "new_content"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co, scaling to production.",
     ["new_content"]),
    ("Reduced latency by 40% across 2 APIs.", "Cut latency by 40% across 2 APIs.", []),
    ("Reduced latency by 40% across 2 APIs.", "Reduced latency by 45% across 2 APIs.", ["quantity_changed"]),
    ("Reduced latency to 92 ms.", "Reduced latency to 90 ms.", ["quantity_changed"]),
    ("Studying Kafka.", "Certified in Kafka.", ["credential_added"]),
    ("Studying Kafka.", "Completed Kafka studies.", ["credential_added", "new_content"]),
    ("Worked from 2022 to 2024.", "Worked from 2021 to 2024.", ["quantity_changed"]),
    ("Worked from 2022 to 2024.", "From 2022 to 2024, worked.", []),
    ("No production on-call experience.", "Production on-call experience.", ["negation_changed"]),
    ("Built Python services.", "   ", ["empty"]),
]


class GuardCorpus(unittest.TestCase):
    def test_labelled_corpus(self):
        for claim, text, expected in CORPUS:
            with self.subTest(text=text):
                result = check(claim, text)
                self.assertEqual(sorted(expected), sorted(result["findings"]))
                verdict = "exact" if text == claim else ("guard_pass" if not expected else "reject")
                self.assertEqual(verdict, result["verdict"])

    def test_no_labelled_invention_passes(self):
        # Every corpus row that changes a fact must fail on at least one hard finding.
        hard = [row for row in CORPUS if set(row[2]) - {"new_content"}]
        for claim, text, _ in hard:
            self.assertTrue(set(check(claim, text)["findings"]) - {"new_content"}, text)

    def test_findings_never_echo_text(self):
        result = check(CLAIM, "Led SECRET-777 services for 9 teams at Fixture Co.")
        self.assertNotIn("SECRET", canonical(result))


class ParaphraseLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(self.ws.close)
        self.tasks = Tasks(self.ws)
        self.source = self.ws.import_source(CLAIM.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(CLAIM))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Engineer", "description": "Python",
                                    "requirements": ["Python"]})["job_id"]
        self.reworded = "For 3 internal teams at Fixture Co, built Python services."

    def submit(self, text, claim=None):
        task = self.tasks.create(self.job, "draft_cv", consent=True)["task_id"]
        response = {"output": {"assertions": [{"text": text, "claim_id": claim or self.claim}]},
                    "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}
        return task, lambda: self.tasks.submit(task, canonical(response).encode())

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_unapproved_paraphrase_is_rejected_then_accepted_after_approval(self):
        _, run = self.submit(self.reworded)
        error = self.assertCode("unsupported_assertion", run)
        self.assertNotIn("Fixture", str(error))
        self.ws.approve_paraphrase(self.claim, self.reworded, True)
        task, run = self.submit(self.reworded)
        self.assertEqual(self.reworded, json.loads(self.ws.store.one("tasks", task)["packet"])
                         ["evidence"][0]["approved_paraphrases"][0])
        self.assertFalse(run()["ready"])

    def test_model_invention_reports_guard_codes(self):
        _, run = self.submit("Led Python services for 30 internal teams at Fixture Co.")
        error = self.assertCode("unsupported_assertion", run)
        self.assertIn("quantity_changed", str(error))
        self.assertIn("scope_escalation", str(error))

    def test_hard_findings_cannot_be_acknowledged(self):
        self.assertCode("paraphrase_rejected", self.ws.approve_paraphrase, self.claim,
                        "Led Python services for 3 internal teams at Fixture Co.", True)
        self.assertCode("invalid_schema", self.ws.approve_paraphrase, self.claim,
                        "Led Python services for 3 internal teams at Fixture Co.", True, ["scope_escalation"])
        self.assertCode("confirmation_required", self.ws.approve_paraphrase, self.claim, self.reworded, False)
        self.assertCode("invalid_schema", self.ws.approve_paraphrase, self.claim, CLAIM, True)

    def test_new_content_requires_acknowledgement(self):
        text = CLAIM[:-1] + ", scaling to production."
        self.assertCode("paraphrase_rejected", self.ws.approve_paraphrase, self.claim, text, True)
        result = self.ws.approve_paraphrase(self.claim, text, True, ["new_content"])
        self.assertEqual(["new_content"], result["findings"])

    def test_revocation_and_correction_make_tasks_stale(self):
        approved = self.ws.approve_paraphrase(self.claim, self.reworded, True)
        task, run = self.submit(self.reworded)
        self.ws.revoke_paraphrase(approved["paraphrase_id"])
        self.assertCode("stale_input", run)
        self.ws.approve_paraphrase(self.claim, self.reworded, True)
        corrected = self.ws.correct_claim(self.claim, CLAIM.replace("3", "4"))
        self.ws.publish_profile()
        self.assertEqual([], self.ws.paraphrases(self.claim))
        _, run = self.submit(self.reworded, corrected["claim_id"])
        self.assertCode("unsupported_assertion", run)

    def test_deletion_erases_paraphrase_text(self):
        self.ws.approve_paraphrase(self.claim, self.reworded, True)
        self.ws.delete_source(self.source)
        rows = self.ws.db.execute("SELECT text,revoked FROM paraphrases").fetchall()
        self.assertTrue(rows and all(r["revoked"] == 1 and "Fixture" not in r["text"] for r in rows))

    def test_cli_check_and_approve(self):
        checked = dispatch(self.ws, "paraphrase-check", {"claim_id": self.claim, "text": self.reworded})
        self.assertEqual("guard_pass", checked["verdict"])
        approved = dispatch(self.ws, "paraphrase-approve",
                            {"claim_id": self.claim, "text": self.reworded, "confirm": True})
        self.assertTrue(dispatch(self.ws, "paraphrase-revoke",
                                 {"paraphrase_id": approved["paraphrase_id"]})["revoked"])


if __name__ == "__main__":
    unittest.main()
