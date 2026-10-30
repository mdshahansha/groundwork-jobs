"""JW-05 paraphrase guard: labelled synthetic corpus plus approval lifecycle. Not entailment."""

from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from jw.cli import dispatch
from jw.contracts import WorkspaceError, canonical
from jw.semantics import check
from jw.store import Store
from jw.tasks import Tasks
from jw.workspace import Workspace

CORPUS_FILE = Path(__file__).parent / "fixtures" / "jw_paraphrase_corpus.json"
CLAIM = "Built Python services for 3 internal teams at Fixture Co."

# (claim, candidate wording, expected findings). Empty findings means the guard passes.
CORPUS = [
    (CLAIM, CLAIM, []),
    (CLAIM, "For 3 internal teams at Fixture Co, built Python services.", []),
    (CLAIM, "Built Python services for 3 teams at Fixture Co.", []),
    (CLAIM, "Built Python services for 4 internal teams at Fixture Co.", ["quantity_changed"]),
    (CLAIM, "Built Python services for internal teams at Fixture Co.", ["quantity_changed"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co and Acme.", ["entity_added", "new_content"]),
    (CLAIM, "Built Python and Go services for 3 internal teams at Fixture Co.", ["entity_added", "new_content"]),
    (CLAIM, "Led Python services for 3 internal teams at Fixture Co.", ["scope_escalation"]),
    (CLAIM, "Built all Python services for 3 internal teams at Fixture Co.", ["scope_escalation"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co as a senior engineer.",
     ["scope_escalation", "new_content"]),
    (CLAIM, "Did not build Python services for 3 internal teams at Fixture Co.", ["negation_changed", "new_content"]),
    (CLAIM, "Built Python services for 3 internal teams at Fixture Co, scaling to production.",
     ["new_content"]),
    ("Reduced latency by 40% across 2 APIs.", "Cut latency by 40% across 2 APIs.", ["new_content"]),
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

    def test_release_corpus_recall_and_false_rejects(self):
        rows = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))["rows"]
        changes = [r for r in rows if r["label"] == "changes"]
        preserves = [r for r in rows if r["label"] == "preserves"]
        self.assertGreaterEqual(len(changes), 100)
        flagged = [r for r in changes if check(r["claim"], r["text"])["findings"]]
        rejected = [r for r in preserves if check(r["claim"], r["text"])["findings"]]
        # Release gate: every fact-changing edit is caught; no meaning-preserving edit is blocked.
        self.assertEqual(1.0, len(flagged) / len(changes), [r["category"] for r in changes if r not in flagged])
        self.assertEqual(0, len(rejected), [r["category"] for r in rejected])
        self.assertEqual(len({r["category"] for r in changes}), 10)

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

    def approve(self, text, claim=None, acknowledge=(), verdict="entailed", codes=()):
        result = self.ws.approve_paraphrase(claim or self.claim, text, True, list(acknowledge), True)
        self.review(result["paraphrase_id"], verdict, codes)
        return result

    def review(self, paraphrase_id, verdict="entailed", codes=()):
        response = {"output": {"verdict": verdict, "codes": list(codes)},
                    "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}
        return self.ws.submit_paraphrase_review(paraphrase_id, canonical(response).encode())

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
        self.approve(self.reworded)
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
        led = "Led Python services for 3 internal teams at Fixture Co."
        self.assertCode("paraphrase_rejected", self.ws.approve_paraphrase, self.claim, led, True, [], True)
        self.assertCode("invalid_schema", self.ws.approve_paraphrase, self.claim, led, True,
                        ["scope_escalation"], True)
        self.assertCode("confirmation_required", self.ws.approve_paraphrase, self.claim, self.reworded, False,
                        [], True)
        self.assertCode("consent_required", self.ws.approve_paraphrase, self.claim, self.reworded, True)
        self.assertCode("invalid_schema", self.ws.approve_paraphrase, self.claim, CLAIM, True, [], True)

    def test_new_content_requires_acknowledgement(self):
        text = CLAIM[:-1] + ", scaling to production."
        self.assertCode("paraphrase_rejected", self.ws.approve_paraphrase, self.claim, text, True, [], True)
        result = self.approve(text, acknowledge=["new_content"])
        self.assertEqual(["new_content"], result["findings"])
        self.assertIn(text, self.ws.paraphrases(self.claim))

    def test_revocation_and_correction_make_tasks_stale(self):
        approved = self.approve(self.reworded)
        task, run = self.submit(self.reworded)
        self.ws.revoke_paraphrase(approved["paraphrase_id"])
        self.assertCode("stale_input", run)
        self.approve(self.reworded)
        corrected = self.ws.correct_claim(self.claim, CLAIM.replace("3", "4"))
        self.ws.publish_profile()
        self.assertEqual([], self.ws.paraphrases(self.claim))
        _, run = self.submit(self.reworded, corrected["claim_id"])
        self.assertCode("unsupported_assertion", run)

    def test_deletion_erases_paraphrase_text(self):
        self.approve(self.reworded)
        self.ws.delete_source(self.source)
        rows = self.ws.db.execute("SELECT text,revoked FROM paraphrases").fetchall()
        self.assertTrue(rows and all(r["revoked"] == 1 and "Fixture" not in r["text"] for r in rows))

    def test_cli_check_and_approve(self):
        checked = dispatch(self.ws, "paraphrase-check", {"claim_id": self.claim, "text": self.reworded})
        self.assertEqual("guard_pass", checked["verdict"])
        approved = dispatch(self.ws, "paraphrase-approve",
                            {"claim_id": self.claim, "text": self.reworded, "confirm": True, "consent": True})
        packet = dispatch(self.ws, "paraphrase-review-packet", {"paraphrase_id": approved["paraphrase_id"]})
        self.assertEqual([], packet["allowed_tools"])
        reviewed = dispatch(self.ws, "paraphrase-review-submit", {
            "paraphrase_id": approved["paraphrase_id"],
            "response": {"output": {"verdict": "entailed", "codes": []},
                         "usage": {"model": "synthetic-fixture", "input_tokens": 1, "output_tokens": 1}}})
        self.assertEqual("entailed", reviewed["review"])
        self.assertTrue(dispatch(self.ws, "paraphrase-revoke",
                                 {"paraphrase_id": approved["paraphrase_id"]})["revoked"])


class EntailmentReview(ParaphraseLifecycle):
    """The host-model verdict is a second gate after the guard and candidate approval."""

    def test_unreviewed_paraphrase_is_not_evidence(self):
        result = self.ws.approve_paraphrase(self.claim, self.reworded, True, [], True)
        self.assertEqual("needs_model", result["review"])
        self.assertEqual(self.reworded, result["packet"]["candidate_wording"])
        self.assertEqual([], self.ws.paraphrases(self.claim))
        _, run = self.submit(self.reworded)
        self.assertCode("unsupported_assertion", run)

    def test_not_entailed_and_uncertain_reject(self):
        for verdict in ("not_entailed", "uncertain"):
            with self.subTest(verdict=verdict):
                text = self.reworded if verdict == "not_entailed" else "Built Python services for 3 teams at Fixture Co."
                result = self.approve(text, verdict=verdict, codes=["meaning_changed"])
                self.assertEqual([], self.ws.paraphrases(self.claim))
                self.assertCode("task_not_pending", self.review, result["paraphrase_id"])

    def test_invalid_verdicts_consume_bounded_attempts(self):
        result = self.ws.approve_paraphrase(self.claim, self.reworded, True, [], True)
        pid = result["paraphrase_id"]
        self.assertCode("invalid_schema", self.review, pid, "entailed", ["meaning_changed"])
        self.assertCode("invalid_schema", self.review, pid, "not_entailed", [])
        self.assertCode("invalid_schema", self.review, pid, "maybe")
        self.assertCode("task_not_pending", self.review, pid)
        row = self.ws.db.execute("SELECT review,review_attempts FROM paraphrases WHERE id=?", (pid,)).fetchone()
        self.assertEqual(("blocked_schema", 3), (row["review"], row["review_attempts"]))

    def test_reapproval_requires_fresh_review(self):
        approved = self.approve(self.reworded)
        self.ws.revoke_paraphrase(approved["paraphrase_id"])
        again = self.ws.approve_paraphrase(self.claim, self.reworded, True, [], True)
        self.assertEqual(approved["paraphrase_id"], again["paraphrase_id"])
        self.assertEqual([], self.ws.paraphrases(self.claim))

    def test_private_claim_cannot_be_sent_for_review(self):
        text = "Private synthetic detail for 2 teams."
        source = self.ws.import_source(text.encode(), sensitivity="private")["source_id"]
        claim = self.ws.add_claim(source, 0, len(text))["claim_id"]
        self.assertCode("policy_denied", self.ws.approve_paraphrase, claim,
                        "For 2 teams, private synthetic detail.", True, [], True)

    def test_correction_blocks_pending_review(self):
        result = self.ws.approve_paraphrase(self.claim, self.reworded, True, [], True)
        self.ws.correct_claim(self.claim, CLAIM.replace("3", "4"))
        self.assertCode("task_not_pending", self.review, result["paraphrase_id"])

    def test_schema_3_rows_fail_closed_after_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ws = Workspace(root, create=True)
            text = "Built tools for 2 teams."
            source = ws.import_source(text.encode(), sensitivity="public")["source_id"]
            claim = ws.add_claim(source, 0, len(text))["claim_id"]
            ws.close()
            db = sqlite3.connect(root / "workspace.sqlite3")
            db.execute("CREATE TABLE p AS SELECT id,claim_id,text,guard,acknowledged,approved_at,revoked FROM paraphrases")
            db.execute("DROP TABLE paraphrases")
            db.execute("ALTER TABLE p RENAME TO paraphrases")
            db.execute("INSERT INTO paraphrases VALUES ('par_old',?,?,'guard-1','[]','2026-10-30T00:00:00+00:00',0)",
                       (claim, "For 2 teams, built tools."))
            db.execute("PRAGMA user_version=3")
            db.commit()
            db.close()
            Store(root).close()
            ws = Workspace(root)
            self.assertEqual([], ws.paraphrases(claim))
            self.assertEqual("needs_model", ws.db.execute(
                "SELECT review FROM paraphrases WHERE id='par_old'").fetchone()[0])
            ws.close()


if __name__ == "__main__":
    unittest.main()
