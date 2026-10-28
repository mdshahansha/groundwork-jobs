"""Exact calculation vectors and honest unknown/eligibility boundaries."""

from decimal import Decimal, localcontext
import unittest

from jw.contracts import WorkspaceError
from jw.ranking import experience, experience_band, order_rankings, salary_fit, score, skill_mean


def assessment(**changes):
    value = dict(title_alias_match=True, seniority_distance=0, domain="supported",
                 location="exact", location_eligible=True, candidate_salary=None,
                 job_salary=None, posted_on="2026-10-01", contact="official")
    value.update(changes)
    return value


def salary(low=100, high=200, **changes):
    value = dict(min=low, max=high, currency="USD", basis="base", period="year")
    value.update(changes)
    return value


class RankingTests(unittest.TestCase):
    def test_exact_full_and_mixed_score(self):
        config = assessment(candidate_salary=salary(), job_salary=salary())
        self.assertEqual(100, score(["supported"], ["supported"], config, "2026-10-01")["score"])
        result = score(["supported", "partial", "unsupported", "unknown"], [],
                       assessment(seniority_distance=1, domain="partial", location="relocation",
                                  contact="named_recruiter"), "2026-10-16")
        self.assertEqual(49.31, result["score"])
        self.assertEqual(71.25, result["confidence"])
        self.assertEqual("review", result["recommendation"])

    def test_empty_skills_and_all_unknown_are_finite(self):
        self.assertEqual((Decimal("0.5"), Decimal(0)), skill_mean([]))
        config = assessment(title_alias_match=None, seniority_distance=None, domain="unknown",
                            location="unclear", location_eligible=None, posted_on=None, contact="unknown")
        result = score([], [], config, "2026-10-01")
        self.assertEqual((50, 0, []), (result["score"], result["confidence"], result["exclusions"]))
        self.assertEqual(38.75, score(["unknown"], ["unknown"], config, "2026-10-01")["score"])

    def test_hard_location_wins_even_with_high_score(self):
        result = score(["supported"], [], assessment(location_eligible=False), "2026-10-01")
        self.assertEqual(["LOCATION_MISMATCH"], result["exclusions"])
        self.assertEqual("skip", result["recommendation"])

    def test_salary_incompatible_basis_currency_or_unknown_hours(self):
        for right in (salary(basis="ctc"), salary(currency="INR"), salary(period="hour"), None):
            self.assertEqual((Decimal("0.5"), Decimal(0)), salary_fit(salary(), right))

    def test_salary_interval_point_and_normalization(self):
        self.assertEqual((Decimal("0.5"), Decimal(1)), salary_fit(salary(), salary(150, 250)))
        self.assertEqual((Decimal(0), Decimal(1)), salary_fit(salary(), salary(201, 300)))
        self.assertEqual((Decimal(1), Decimal(1)), salary_fit(salary(150, 150), salary()))
        self.assertEqual((Decimal(1), Decimal(1)), salary_fit(salary(1200, 2400), salary(period="month")))
        self.assertEqual((Decimal(1), Decimal(1)), salary_fit(salary(2080, 4160), salary(1, 2, period="hour", hours_per_week=40)))

    def test_salary_rejects_nonfinite_bool_and_reversed(self):
        for invalid in (salary(float("nan"), 200), salary(True, 200), salary(201, 100),
                        salary(period="hour", hours_per_week=0)):
            with self.assertRaises(WorkspaceError):
                salary_fit(invalid, salary())

    def test_freshness_old_future_unknown_and_boundary(self):
        for posted, expected, known in (("2026-09-01", 0, 1), ("2026-10-02", .5, 0), (None, .5, 0)):
            component = score([], [], assessment(posted_on=posted), "2026-10-01")["components"]["freshness"]
            self.assertEqual((expected, known), (component["value"], component["known"]))

    def test_overlaps_count_once_and_order_does_not_matter(self):
        records = [{"start": "2024-01-01", "end": "2024-07-01"},
                   {"start": "2024-06-01", "end": "2025-01-01"}]
        result = experience(records, "2026-10-01")
        self.assertEqual(366, result["days"])
        self.assertEqual(1.0, result["years"])
        self.assertEqual(result, experience(records[::-1] + records, "2026-10-01"))

    def test_partial_months_and_current_role_are_conservative(self):
        self.assertEqual(1, experience([{"start": "2024-01", "end": "2024-02"}], "2026-10-01")["days"])
        self.assertEqual(0, experience([{"start": "2024-01", "end": "2024-01"}], "2026-10-01")["days"])
        self.assertEqual(30, experience([{"start": "2026-09-01", "end": None}], "2026-10-01")["days"])

    def test_experience_preference_is_separate(self):
        self.assertEqual("unknown", experience_band(None, 3, 5))
        self.assertEqual("below", experience_band(2.99, 3, 5))
        self.assertEqual("within", experience_band(3, 3, 5))
        self.assertEqual("above", experience_band(6, 3, 5))
        with self.assertRaises(WorkspaceError):
            experience_band(4, 5, 3)

    def test_bad_enums_dates_and_bool_distance(self):
        for config in (assessment(domain=[]), assessment(seniority_distance=True),
                       assessment(location="not_applicable"), assessment(posted_on="2026-02-30")):
            with self.assertRaises(WorkspaceError):
                score([], [], config, "2026-10-01")

    def test_ambient_decimal_context_cannot_change_score(self):
        expected = score(["partial"], [], assessment(), "2026-10-01")
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(expected, score(["partial"], [], assessment(), "2026-10-01"))

    def test_ties_are_stable_and_excluded_jobs_stay_last(self):
        rows = [{"job_id": "b", "score": 50, "exclusions": []},
                {"job_id": "a", "score": 50, "exclusions": []},
                {"job_id": "c", "score": 100, "exclusions": ["LOCATION_MISMATCH"]}]
        self.assertEqual(["a", "b", "c"], [r["job_id"] for r in order_rankings(rows)])
        self.assertEqual(order_rankings(rows), order_rankings(rows[::-1]))


if __name__ == "__main__":
    unittest.main()
