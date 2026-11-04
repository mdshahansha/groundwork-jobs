"""JW-07: versioned ranking policy, FR-RNK-01 hard constraints, preferred requirements,
host-model requirement mapping review and pinned rankings. Synthetic data only."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jw.cli import main
from jw.contracts import WorkspaceError, canonical, utcnow
from jw.policy import validate
from jw.store import Store
from jw.workspace import Workspace
from test_jw_ranking import assessment, policy


def review(verdict, codes=()):
    return canonical({"output": {"verdict": verdict, "codes": list(codes)},
                      "usage": {"model": "synthetic-fixture", "input_tokens": None, "output_tokens": None}}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws.close())
        text = "Deployed services with Docker Compose and Python."
        self.source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.claim = self.ws.add_claim(self.source, 0, len(text))["claim_id"]
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()

    def job(self, **changes):
        data = {"company": "Fixture Co", "title": "Platform Engineer", "description": "Synthetic listing.",
                "requirements": ["Python", "Kubernetes"]}
        data.update(changes)
        return self.ws.add_job(data)["job_id"]

    def mapping(self, *states):
        return [{"index": i, "state": s, "claim_id": self.claim if s in ("supported", "partial") else None}
                for i, s in enumerate(states)]

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception


class PolicyValidation(Base):
    def test_unknown_key_names_path_and_suggestion(self):
        bad = policy()
        bad["relevance_treshold"] = bad.pop("relevance_threshold")
        error = self.assertCode("policy_invalid", validate, bad)
        self.assertIn("relevance_treshold", str(error))
        self.assertIn('Did you mean "relevance_threshold"', str(error))
        nested = policy(freshness={"max_age_days": 30, "max_ag_days": 3})
        self.assertIn("freshness.max_ag_days", str(self.assertCode("policy_invalid", validate, nested)))

    def test_bounds_enums_and_legacy_weights_are_refused(self):
        for bad in (policy(relevance_threshold=101), policy(freshness={"max_age_days": 91}),
                    policy(location={"countries": [], "remote": "no"}),
                    policy(location={"countries": ["india"], "remote": "allowed"}),
                    policy(eligibility={"country": "in"}), policy(weights="weights@0"),
                    policy(history={"exclude_applied_within_days": True}), policy(schema="ranking-policy@2")):
            self.assertCode("policy_invalid", validate, bad)

    def test_hash_is_stable_under_order_case_and_whitespace(self):
        left = validate(policy(companies={"deny": ["Acme  Corp", "beta"]}))[1]
        right = validate(policy(companies={"deny": ["Beta", "acme corp"]}))[1]
        self.assertEqual(left, right)
        self.assertNotEqual(left, validate(policy(relevance_threshold=61))[1])

    def test_missing_policy_blocks_ranking(self):
        job = self.job()
        self.assertCode("policy_missing", self.ws.rank, job, self.mapping("supported", "unknown"), assessment())

    def test_invalid_edit_leaves_previous_policy_active(self):
        first = self.ws.set_policy(policy())["policy_hash"]
        self.assertCode("policy_invalid", self.ws.set_policy, policy(relevance_threshold=-1))
        self.assertEqual(first, self.ws.active_policy()[1])


class PinnedRankings(Base):
    def test_policy_change_marks_rankings_outdated_not_deleted(self):
        first = self.ws.set_policy(policy())["policy_hash"]
        job = self.job()
        ranked = self.ws.rank(job, self.mapping("supported", "unknown"), assessment())
        self.assertEqual(first, ranked["policy_hash"])
        self.assertEqual([ranked["ranking_id"]], [r["ranking_id"] for r in self.ws.rankings()["shortlist"]])
        again = self.ws.set_policy(policy())
        self.assertEqual((False, 0), (again["changed"], again["rankings_outdated"]))
        changed = self.ws.set_policy(policy(relevance_threshold=10))
        self.assertEqual((True, 1), (changed["changed"], changed["rankings_outdated"]))
        listing = self.ws.rankings(include_outdated=True)
        self.assertEqual([], listing["shortlist"])
        self.assertEqual([(ranked["ranking_id"], first)],
                         [(r["ranking_id"], r["policy_hash"]) for r in listing["outdated"]])
        self.assertEqual(changed["policy_hash"], listing["policy_hash"])

    def test_rerank_supersedes_and_deletion_outdates(self):
        self.ws.set_policy(policy())
        job = self.job()
        first = self.ws.rank(job, self.mapping("supported", "unknown"), assessment())["ranking_id"]
        second = self.ws.rank(job, self.mapping("supported", "unsupported"), assessment())["ranking_id"]
        listing = self.ws.rankings(include_outdated=True)
        self.assertEqual([second], [r["ranking_id"] for r in listing["shortlist"]])
        self.assertEqual([first], [r["ranking_id"] for r in listing["outdated"]])
        self.ws.delete_source(self.source)
        self.assertEqual([], self.ws.rankings()["shortlist"])

    def test_threshold_and_risk_flags_drive_recommendation(self):
        self.ws.set_policy(policy(relevance_threshold=60))
        job = self.job()
        strong = self.ws.rank(job, self.mapping("supported", "partial"), assessment())
        self.assertEqual("review", strong["recommendation"])
        self.assertEqual(["credibility_unassessed", "availability_unverified"], strong["recommendation_reasons"])
        weak = self.ws.rank(job, self.mapping("unsupported", "unsupported"),
                            assessment(domain="unsupported", location="mismatch", title_alias_match=False))
        self.assertEqual(("skip", ["below_threshold"]), (weak["recommendation"], weak["recommendation_reasons"]))
        self.ws.set_policy(policy(relevance_threshold=0))
        vague = self.ws.rank(job, self.mapping("unknown", "unknown"),
                             assessment(title_alias_match=None, domain="unknown", location="unclear",
                                        posted_on=None, contact="unknown"))
        self.assertIn("many_unknowns", vague["recommendation_reasons"])
        self.assertIn({"component": "salary", "label": "salary unknown or not overlapping"}, vague["gaps"])

    def test_policy_owns_freshness_window(self):
        self.ws.set_policy(policy())
        job = self.job()
        self.assertCode("invalid_schema", self.ws.rank, job, self.mapping("supported", "unknown"),
                        assessment(freshness_window_days=10))


class HardConstraints(Base):
    def codes(self, job, preferred=None, **policy_changes):
        self.ws.set_policy(policy(**policy_changes))
        return self.ws.rank(job, self.mapping("supported", "unknown"), assessment(), preferred)

    def test_every_policy_code_names_rule_and_value(self):
        job = self.job(company="Acme  Corp", remote_regions=["US"], required_authorisations=["US work authorisation"],
                       mandatory_credentials=["CPA licence"], requirements=["Python", "Kubernetes clearance"])
        result = self.codes(job, companies={"deny": ["acme corp"]}, skills={"excluded_terms": ["clearance"]},
                            eligibility={"country": "IN", "authorisations_not_held": ["us work authorisation"],
                                         "credentials_absent": ["CPA Licence"]})
        self.assertEqual(["COMPANY_DENIED", "EXCLUDED_TERM", "REMOTE_REGION_MISMATCH", "AUTHORISATION_NOT_HELD",
                          "MANDATORY_CREDENTIAL_MISSING"], result["exclusions"])
        self.assertEqual("skip", result["recommendation"])
        self.assertEqual({"code": "REMOTE_REGION_MISMATCH", "rule": "job.remote_regions", "value": "US excludes IN"},
                         result["exclusion_details"][2])
        self.assertEqual(result["exclusions"], self.ws.rankings()["shortlist"][0]["exclusions"])

    def test_unknowns_never_exclude(self):
        job = self.job(remote_regions=["US"], required_authorisations=["US work authorisation"],
                       mandatory_credentials=["CPA licence"])
        result = self.codes(job, eligibility={"country": None})
        self.assertEqual([], result["exclusions"])
        self.assertEqual([], self.codes(self.job(remote_regions=["IN", "US"]))["exclusions"])

    def test_excluded_term_is_whole_phrase(self):
        job = self.job(requirements=["Python", "Javascript"])
        self.assertEqual([], self.codes(job, skills={"excluded_terms": ["java"]})["exclusions"])
        job = self.job(preferred_requirements=["Java"])
        unknown = [{"index": 0, "state": "unknown", "claim_id": None}]
        self.assertEqual(["EXCLUDED_TERM"], self.codes(job, unknown, skills={"excluded_terms": ["java"]})["exclusions"])

    def test_already_applied_within_window(self):
        job = self.job()
        self.ws.record_outcome(job, "manual_applied", utcnow())
        self.assertEqual([], self.codes(job)["exclusions"])
        result = self.codes(job, history={"exclude_applied_within_days": 30})
        self.assertEqual(["ALREADY_APPLIED"], result["exclusions"])

    def test_location_eligibility_still_excludes_first(self):
        self.ws.set_policy(policy())
        result = self.ws.rank(self.job(), self.mapping("supported", "unknown"), assessment(location_eligible=False))
        self.assertEqual("LOCATION_MISMATCH", result["exclusions"][0])


class PreferredRequirements(Base):
    def test_preferred_requirements_are_stored_mapped_and_weighted(self):
        self.ws.set_policy(policy())
        job = self.job(preferred_requirements=["Python"])
        self.assertCode("invalid_schema", self.ws.rank, job, self.mapping("supported", "unknown"), assessment())
        preferred = [{"index": 0, "state": "supported", "claim_id": self.claim}]
        result = self.ws.rank(job, self.mapping("supported", "unknown"), assessment(), preferred)
        self.assertEqual((1.0, 10), (result["components"]["preferred"]["value"],
                                     result["components"]["preferred"]["weight"]))
        self.assertEqual(["required", "required", "preferred"], [m["group"] for m in result["requirement_matrix"]])
        without = self.ws.rank(self.job(), self.mapping("supported", "unknown"), assessment())
        self.assertEqual((0.5, 0), (without["components"]["preferred"]["value"],
                                    without["components"]["preferred"]["known"]))

    def test_job_fields_are_validated(self):
        self.assertCode("invalid_schema", self.job, remote_regions=["usa"])
        self.assertCode("invalid_schema", self.job, preferred_requirements="Python")
        self.assertCode("invalid_schema", self.job, salary="1")


class SemanticMapping(Base):
    def setUp(self):
        super().setUp()
        self.ws.set_policy(policy())
        self.job_id = self.job(requirements=["Python", "container deployment", "Kubernetes"])

    def propose(self, index):
        return self.ws.propose_mapping(self.job_id, "required", index, self.claim, True)

    def test_direct_review_admits_supported_without_phrase(self):
        mapping = self.mapping("supported", "supported", "unknown")
        self.assertCode("unsupported_mapping", self.ws.rank, self.job_id, mapping, assessment())
        proposal = self.propose(1)
        packet = proposal["packet"]
        self.assertEqual(([], "container deployment"), (packet["allowed_tools"], packet["requirement"]))
        self.assertIn("never `direct`", packet["instructions"])
        self.ws.submit_mapping_review(proposal["mapping_review_id"], review("direct"))
        result = self.ws.rank(self.job_id, mapping, assessment())
        self.assertEqual(["lexical", "model_reviewed_direct", "candidate_assessed"],
                         [m["evidence_label"] for m in result["requirement_matrix"]])

    def test_related_review_never_becomes_supported(self):
        proposal = self.propose(2)
        self.assertEqual("related", self.ws.submit_mapping_review(
            proposal["mapping_review_id"], review("related", ["transferable_only"]))["review"])
        self.assertCode("unsupported_mapping", self.ws.rank, self.job_id,
                        self.mapping("supported", "unknown", "supported"), assessment())
        partial = self.ws.rank(self.job_id, self.mapping("supported", "unknown", "partial"), assessment())
        self.assertEqual("related", partial["requirement_matrix"][2]["evidence_label"])

    def test_verdicts_are_closed_immutable_and_attempt_capped(self):
        review_id = self.propose(2)["mapping_review_id"]
        for bad in (review("direct", ["different_skill"]), review("none"), review("maybe", ["different_skill"]),):
            self.assertCode("invalid_schema", self.ws.submit_mapping_review, review_id, bad)
        self.assertEqual("blocked_schema", self.ws.store.one("requirement_reviews", review_id)["review"])
        self.assertCode("task_not_pending", self.ws.submit_mapping_review, review_id, review("direct"))
        self.assertCode("task_not_pending", self.propose, 2)
        other = self.propose(1)["mapping_review_id"]
        self.ws.submit_mapping_review(other, review("none", ["different_skill"]))
        self.assertCode("task_not_pending", self.ws.submit_mapping_review, other, review("direct"))

    def test_consent_eligibility_and_correction(self):
        self.assertCode("consent_required", self.ws.propose_mapping, self.job_id, "required", 1, self.claim, False)
        self.assertCode("invalid_schema", self.ws.propose_mapping, self.job_id, "preferred", 0, self.claim, True)
        review_id = self.propose(1)["mapping_review_id"]
        self.ws.submit_mapping_review(review_id, review("direct"))
        corrected = self.ws.correct_claim(self.claim, "Deployed Python services.")["claim_id"]
        self.ws.publish_profile()
        mapping = self.mapping("supported", "supported", "unknown")
        self.assertCode("unknown_claim", self.ws.rank, self.job_id, mapping, assessment())
        for item in mapping[:2]:
            item["claim_id"] = corrected
        # A verdict binds to the exact claim it reviewed: the correction needs its own review.
        self.assertCode("unsupported_mapping", self.ws.rank, self.job_id, mapping, assessment())

    def test_stale_claim_blocks_pending_review_and_deletion_revokes(self):
        pending = self.propose(1)["mapping_review_id"]
        done = self.propose(2)["mapping_review_id"]
        self.ws.submit_mapping_review(done, review("related", ["transferable_only"]))
        self.ws.delete_source(self.source)
        self.assertEqual("revoked", self.ws.store.one("requirement_reviews", done)["review"])
        self.assertCode("task_not_pending", self.ws.submit_mapping_review, pending, review("direct"))


class CommandsAndMigration(Base):
    def run_cli(self, command, payload=None):
        args = ["--workspace", str(self.root), command]
        if payload is not None:
            request = Path(self.temp.name) / (command + ".json")
            request.write_text(canonical(payload), encoding="utf-8")
            args += ["--input", str(request)]
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_cli_policy_mapping_rank_and_rankings(self):
        self.ws.close()
        code, out = self.run_cli("policy-set", {"policy": dict(policy(), max_resuls=5)})
        self.assertEqual((2, "policy_invalid"), (code, out["error"]["code"]))
        code, out = self.run_cli("policy-set", {"policy": policy()})
        self.assertEqual(0, code)
        self.assertEqual(out["result"]["policy_hash"], self.run_cli("policy-show")[1]["result"]["policy_hash"])
        self.ws = Workspace(self.root)
        job = self.job(requirements=["container deployment"])
        self.ws.close()
        code, out = self.run_cli("mapping-propose", {"job_id": job, "group": "required", "index": 0,
                                                     "claim_id": self.claim, "consent": True})
        review_id = out["result"]["mapping_review_id"]
        code, out = self.run_cli("mapping-review-submit", {"mapping_review_id": review_id,
                                 "response": json.loads(review("direct"))})
        self.assertEqual("direct", out["result"]["review"])
        code, out = self.run_cli("rank", {"job_id": job, "assessment": assessment(),
                                          "mapping": [{"index": 0, "state": "supported", "claim_id": self.claim}]})
        self.assertEqual(0, code)
        code, out = self.run_cli("rankings", {})
        self.assertEqual(1, len(out["result"]["shortlist"]))
        self.ws = Workspace(self.root)

    def test_v4_workspace_upgrades_to_v5(self):
        self.ws.close()
        db = sqlite3.connect(self.root / "workspace.sqlite3")
        for table in ("rankings", "requirement_reviews", "active_policy", "policies"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=4")
        db.commit()
        db.close()
        Store(self.root).close()
        self.ws = Workspace(self.root)
        self.assertEqual(5, self.ws.db.execute("PRAGMA user_version").fetchone()[0])
        self.assertCode("policy_missing", self.ws.active_policy)
        self.assertEqual(5, self.ws.status()["schema_version"])


if __name__ == "__main__":
    unittest.main()
