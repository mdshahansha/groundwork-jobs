"""JW-10: FR-DOC-06 independent review. One test per acceptance case: what the reviewer
receives, and every way a finding can be refused. Model review quality is not measured here."""

import json
import unittest

from jw.contracts import canonical
from jw.tasks import REVIEW_CODES, SEVERITY_RANK
from test_jw_model_tasks import Repair, response


def finding(**overrides):
    item = {"severity": "critical", "code": "fabricated_qualification", "assertion_index": 0,
            "location": {"page": 1, "line": 5, "element": "assertion"},
            "claim_ids": [], "proposed_correction": "Remove the claim.", "blocking": True}
    item.update(overrides)
    return item


class IndependentReview(Repair):
    def review_task(self, draft=None):
        # Identical drafts are reused, and a completed draft refuses a second submit: draft once per test.
        if draft is None:
            if not hasattr(self, "_draft"):
                self._draft = self.drafted()
            draft = self._draft
        return self.tasks.create(self.job, "review", consent=True, draft_id=draft)["task_id"]

    def packet(self, review):
        return self.tasks.packet(review)["packet"]

    def refused(self, code, findings, review=None):
        # Validate without submitting: identical tasks are reused, and each submit spends an attempt.
        task = self.ws.store.one("tasks", review or self.review_task())
        self.assertCode(code, self.tasks._validate, task, {"findings": findings})

    def test_packet_holds_only_the_fr_doc_06_inputs(self):
        packet = self.packet(self.review_task())
        for key in ("draft", "rendered", "cited_evidence", "requirement_matrix", "document_policy", "style_guide"):
            self.assertIn(key, packet)
        for key in ("evidence", "rationale", "history", "messages", "self_approval", "blocking_findings"):
            self.assertNotIn(key, packet)

    def test_cited_evidence_is_only_the_claims_the_draft_uses(self):
        draft = self.tasks.create(self.job, "draft_cv", consent=True)["task_id"]
        self.tasks.submit(draft, response({"assertions": [self.assertion(0)]}))
        packet = self.packet(self.review_task(draft))
        self.assertEqual([self.claims[0]], [c["claim_id"] for c in packet["cited_evidence"]])

    def test_rendered_text_comes_from_the_pdf_and_page_images_are_not_claimed(self):
        rendered = self.packet(self.review_task())["rendered"]
        self.assertIn(self.assertion(0)["text"], rendered["text"])
        self.assertEqual("mechanical_passed", rendered["mechanical_status"])
        self.assertTrue(rendered["page_images"].startswith("not_supplied"))

    def test_requirement_matrix_carries_job_requirements_and_accepted_mappings(self):
        self.ws.db.execute("INSERT INTO requirement_reviews VALUES ('rr1',?,'required',0,?,'direct',1,'t')",
                           (self.job, self.claims[0]))
        self.ws.db.execute("INSERT INTO requirement_reviews VALUES ('rr2',?,'required',0,?,'rejected',1,'t')",
                           (self.job, self.claims[1]))
        self.ws.db.commit()
        matrix = self.packet(self.review_task())["requirement_matrix"]
        self.assertEqual(["Python"], matrix["required"])
        self.assertEqual([self.claims[0]], [m["claim_id"] for m in matrix["reviewed_mappings"]])

    def test_policy_states_the_severity_table(self):
        policy = self.packet(self.review_task())["document_policy"]
        self.assertEqual("critical", policy["severity_floor"]["fabricated_qualification"])
        self.assertEqual(["critical", "major"], policy["blocking_severities"])

    def test_full_finding_is_accepted_and_stored_whole(self):
        review = self.review_task()
        item = finding(claim_ids=[self.claims[0]])
        self.tasks.submit(review, response({"findings": [item]}))
        self.assertEqual([item], json.loads(self.ws.store.one("tasks", review)["output"])["findings"])

    def test_every_code_refuses_a_severity_below_its_floor(self):
        for code, floor in REVIEW_CODES.items():
            for severity, rank in SEVERITY_RANK.items():
                if rank < SEVERITY_RANK[floor]:
                    with self.subTest(code=code, severity=severity):
                        self.refused("severity_below_policy",
                                     [finding(code=code, severity=severity, blocking=severity != "minor")])

    def test_unknown_code_or_severity_is_refused(self):
        self.refused("invalid_schema", [finding(code="made_up")])
        self.refused("invalid_schema", [finding(severity="blocker")])

    def test_blocking_flag_must_match_severity(self):
        self.refused("invalid_schema", [finding(blocking=False)])
        self.refused("invalid_schema", [finding(code="style", severity="minor", blocking=True)])

    def test_bad_locations_are_refused(self):
        for location in ({"page": 2, "line": 1, "element": "assertion"},
                         {"page": 1, "line": 0, "element": "assertion"},
                         {"page": 1, "line": 1, "element": "sidebar"},
                         {"page": 1, "element": "assertion"}):
            with self.subTest(location=location):
                self.refused("invalid_schema", [finding(location=location)])

    def test_finding_cannot_cite_a_claim_the_reviewer_was_not_given(self):
        draft = self.tasks.create(self.job, "draft_cv", consent=True)["task_id"]
        self.tasks.submit(draft, response({"assertions": [self.assertion(0)]}))
        self.refused("unknown_claim", [finding(claim_ids=[self.claims[1]])], self.review_task(draft))

    def test_overlong_correction_is_refused(self):
        self.refused("invalid_schema", [finding(proposed_correction="x" * 2001)])

    def test_full_shape_blocking_finding_drives_repair(self):
        review = self.review_task()
        self.tasks.submit(review, response({"findings": [finding(assertion_index=1)]}))
        repair = self.tasks.create(self.job, "repair", consent=True, draft_id=review)
        packet = self.tasks.packet(repair["task_id"])["packet"]
        self.assertEqual(1, packet["blocking_findings"][0]["assertion_index"])
        self.assertEqual(1, packet["repair_iteration"])

    def test_review_never_reports_ready(self):
        review = self.review_task()
        self.assertNotIn("ready", canonical(self.packet(review)["document_policy"]))
        self.assertFalse(self.tasks.submit(review, response({"findings": []}))["ready"])


if __name__ == "__main__":
    unittest.main()
