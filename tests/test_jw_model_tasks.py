"""JW-08: closed extraction and repair schemas, bounded repair loop and usage metering.
Synthetic model responses only; no real model is called."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.tasks import MAX_REPAIR_ITERATIONS, Tasks
from jw.workspace import Workspace

TEXT = "Built Python services. Led a team of 4. Wrote Go tools."


def response(output, input_tokens=None, output_tokens=None):
    return canonical({"output": output, "usage": {"model": "synthetic-fixture", "input_tokens": input_tokens,
                                                  "output_tokens": output_tokens}}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws.close())
        self.tasks = Tasks(self.ws)
        self.source = self.ws.import_source(TEXT.encode(), sensitivity="public")["source_id"]

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)


class Extraction(Base):
    def spans(self, *pairs):
        return {"claims": [{"start": s, "end": e, "text": TEXT[s:e]} for s, e in pairs]}

    def test_proposals_need_acceptance_before_becoming_claims(self):
        created = self.tasks.extraction_create(self.source, consent=True)
        packet = self.tasks.extraction_packet(created["extraction_id"])["packet"]
        self.assertEqual(([], "model:extract_claims@1", TEXT),
                         (packet["allowed_tools"], packet["method"], packet["untrusted_source"]))
        result = self.tasks.extraction_submit(created["extraction_id"], response(self.spans((0, 22), (23, 39))))
        self.assertEqual(2, result["proposals"])
        self.assertEqual(0, self.ws.db.execute("SELECT count(*) FROM claims").fetchone()[0])
        accepted = self.tasks.extraction_accept(created["extraction_id"], [1], True)
        claim = self.ws.store.one("claims", accepted["claims"][0]["claim_id"])
        self.assertEqual(("Led a team of 4.", "public"), (claim["text"], claim["sensitivity"]))
        self.assertCode("confirmation_required", self.tasks.extraction_accept, created["extraction_id"], [0], False)
        self.assertCode("invalid_schema", self.tasks.extraction_accept, created["extraction_id"], [0, 0], True)
        self.assertTrue(self.tasks.extraction_accept(created["extraction_id"], [1], True)["claims"][0]["reused"])
        self.assertTrue(self.tasks.extraction_create(self.source, consent=True)["reused"])

    def test_tampered_overlapping_and_out_of_range_spans_fail_closed(self):
        extraction = self.tasks.extraction_create(self.source, consent=True)["extraction_id"]
        tampered = {"claims": [{"start": 23, "end": 39, "text": "Led a team of 40."}]}
        self.assertCode("evidence_mismatch", self.tasks.extraction_submit, extraction, response(tampered))
        self.assertCode("invalid_span", self.tasks.extraction_submit, extraction, response(self.spans((0, 22), (10, 30))))
        self.assertCode("invalid_span", self.tasks.extraction_submit, extraction,
                        response({"claims": [{"start": 0, "end": 999, "text": TEXT}]}))
        row = self.ws.store.one("extractions", extraction)
        self.assertEqual(("blocked_schema", None), (row["state"], row["output"]))
        self.assertCode("task_not_pending", self.tasks.extraction_submit, extraction, response(self.spans((0, 22))))

    def test_extra_fields_tool_requests_and_token_budget_are_rejected(self):
        extraction = self.tasks.extraction_create(self.source, consent=True)["extraction_id"]
        output = dict(self.spans((0, 22)), tool_calls=[{"name": "send"}])
        self.assertCode("invalid_schema", self.tasks.extraction_submit, extraction, response(output))
        self.assertCode("budget_exhausted", self.tasks.extraction_submit, extraction,
                        response(self.spans((0, 22)), output_tokens=5000))

    def test_consent_privacy_and_deletion(self):
        self.assertCode("consent_required", self.tasks.extraction_create, self.source)
        private = self.ws.import_source(b"Private salary note.", sensitivity="private")["source_id"]
        self.assertCode("policy_denied", self.tasks.extraction_create, private, consent=True)
        extraction = self.tasks.extraction_create(self.source, consent=True)["extraction_id"]
        self.ws.delete_source(self.source)
        row = self.ws.store.one("extractions", extraction)
        self.assertEqual(("erased", None, None), (row["state"], row["packet"], row["output"]))
        self.assertCode("source_deleted", self.tasks.extraction_packet, extraction)


class Repair(Base):
    def setUp(self):
        super().setUp()
        self.claims = [self.ws.add_claim(self.source, s, e)["claim_id"] for s, e in ((0, 22), (23, 39), (40, 55))]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.job = self.ws.add_job({"company": "Fixture Co", "title": "Engineer", "description": "Synthetic.",
                                    "requirements": ["Python"]})["job_id"]

    def assertion(self, i):
        return {"text": TEXT[(0, 23, 40)[i]:(22, 39, 55)[i]], "claim_id": self.claims[i]}

    def drafted(self):
        task = self.tasks.create(self.job, "draft_cv", consent=True)["task_id"]
        self.tasks.submit(task, response({"assertions": [self.assertion(0), self.assertion(1), self.assertion(2)]}))
        return task

    def reviewed(self, draft, findings):
        review = self.tasks.create(self.job, "review", consent=True, draft_id=draft)["task_id"]
        self.tasks.submit(review, response({"findings": findings}))
        return review

    def test_repair_changes_only_named_assertions(self):
        review = self.reviewed(self.drafted(), [{"severity": "major", "code": "style", "assertion_index": 1}])
        repair = self.tasks.create(self.job, "repair", consent=True, draft_id=review)["task_id"]
        packet = self.tasks.packet(repair)["packet"]
        self.assertEqual(("draft_cv", 1, [1]), (packet["document_kind"], packet["repair_iteration"],
                                                [f["assertion_index"] for f in packet["blocking_findings"]]))
        dropped_other = {"assertions": [self.assertion(1), self.assertion(2)]}
        self.assertCode("repair_out_of_scope", self.tasks.submit, repair, response(dropped_other))
        reordered = {"assertions": [self.assertion(2), self.assertion(0)]}
        self.assertCode("repair_out_of_scope", self.tasks.submit, repair, response(reordered))
        invented = {"assertions": [self.assertion(0), {"text": "Led a team of 40.", "claim_id": self.claims[1]},
                                   self.assertion(2)]}
        self.assertCode("unsupported_assertion", self.tasks.submit, repair, response(invented))
        self.assertEqual("blocked_schema", self.ws.store.one("tasks", repair)["state"])

    def test_repaired_draft_is_reviewable_exportable_and_never_ready(self):
        review = self.reviewed(self.drafted(), [{"severity": "critical", "code": "unsupported_assertion",
                                                 "assertion_index": 1}])
        repair = self.tasks.create(self.job, "repair", consent=True, draft_id=review)["task_id"]
        result = self.tasks.submit(repair, response({"assertions": [self.assertion(0), self.assertion(2)]}))
        self.assertFalse(result["ready"])
        exported = self.tasks.private_export(repair)
        self.assertEqual((False, 2), (exported["ready"], len(exported["claim_map"])))
        second = self.tasks.create(self.job, "review", consent=True, draft_id=repair)
        self.assertEqual("needs_model", second["state"])

    def test_minor_only_review_ends_the_loop(self):
        draft = self.drafted()
        review = self.reviewed(draft, [{"severity": "minor", "code": "style", "assertion_index": 0}])
        self.assertCode("no_blocking_findings", self.tasks.create, self.job, "repair", consent=True, draft_id=review)
        self.assertCode("invalid_schema", self.tasks.create, self.job, "repair", consent=True)
        # A repair repairs a review's findings, not a draft directly.
        self.assertCode("invalid_schema", self.tasks.create, self.job, "repair", consent=True, draft_id=draft)

    def test_exhaustion_is_blocked_quality_with_remaining_findings(self):
        draft = self.drafted()
        finding = [{"severity": "major", "code": "style", "assertion_index": None}]
        for iteration in range(1, MAX_REPAIR_ITERATIONS + 1):
            review = self.reviewed(draft, finding)
            draft = self.tasks.create(self.job, "repair", consent=True, draft_id=review)["task_id"]
            self.assertEqual(iteration, self.tasks.packet(draft)["packet"]["repair_iteration"])
            self.tasks.submit(draft, response({"assertions": [self.assertion(0), self.assertion(1),
                                                              self.assertion(2)]}))
        final = self.tasks.create(self.job, "repair", consent=True, draft_id=self.reviewed(draft, finding))
        self.assertEqual(("blocked_quality", False, finding, 3),
                         (final["state"], final["ready"], final["remaining_findings"], final["repair_iterations"]))

    def test_usage_report_keeps_unknown_separate_from_zero(self):
        draft = self.tasks.create(self.job, "draft_cv", consent=True)["task_id"]
        self.tasks.submit(draft, response({"assertions": [self.assertion(0)]}, input_tokens=120, output_tokens=40))
        letter = self.tasks.create(self.job, "draft_letter", consent=True)["task_id"]
        self.tasks.submit(letter, response({"assertions": [self.assertion(1)]}))
        self.tasks.create(self.job, "review", consent=True, draft_id=draft)
        report = self.tasks.usage_report(self.job)
        self.assertEqual({"input_tokens": 120, "output_tokens": 40}, report["reported_tokens"])
        self.assertEqual({"input_tokens": 2, "output_tokens": 2}, report["tasks_with_unknown_tokens"])
        self.assertEqual((None, "unknown", 3, 12), (report["cost"], report["cost_status"],
                                                   report["task_budget"]["used"], report["task_budget"]["limit"]))
        self.assertEqual([None], [t["model"] for t in report["tasks"] if t["state"] == "needs_model"])

    def test_cli_extraction_and_usage_commands(self):
        self.ws.close()
        request = Path(self.temp.name) / "req.json"

        def run(command, payload):
            request.write_text(canonical(payload), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--workspace", str(self.root), command, "--input", str(request)])
            return code, json.loads(output.getvalue())

        code, out = run("extraction-create", {"source_id": self.source, "consent": True})
        extraction = out["result"]["extraction_id"]
        code, out = run("extraction-submit", {"extraction_id": extraction, "response": json.loads(response(
            {"claims": [{"start": 0, "end": 22, "text": TEXT[:22]}]}))})
        self.assertEqual((0, "completed"), (code, out["result"]["state"]))
        code, out = run("extraction-proposals", {"extraction_id": extraction})
        self.assertEqual(TEXT[:22], out["result"]["proposals"][0]["text"])
        code, out = run("usage-report", {"job_id": self.job})
        self.assertEqual((0, "unknown"), (code, out["result"]["cost_status"]))
        self.ws = Workspace(self.root)


if __name__ == "__main__":
    unittest.main()
