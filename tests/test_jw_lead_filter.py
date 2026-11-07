"""Lead pipeline phase 2: every rule drops with a reason, survivors are ranked by an explained fit."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from jw.lead_filter import screen
from jw.leads import import_leads
from jw.workspace import Workspace

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def post(text, hours=5, author="Recruiter A", url=None):
    when = NOW.timestamp() - hours * 3600
    return {"text": text, "author": author, "url": url,
            "posted_at": datetime.fromtimestamp(when, timezone.utc).isoformat()}


GOOD = "Hiring Node.js Developer, Pune, 2-4 years. Node, React, PostgreSQL, Redis, Docker. Mail jobs@good.example"


class LeadFilterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ws = Workspace(Path(temp.name) / "ws", create=True)
        self.addCleanup(self.ws.close)

    def run_with(self, items, **kw):
        import_leads(self.ws, "linkedin_posts", items)
        return screen(self.ws, now=NOW, **kw)

    def test_each_rule_drops_with_its_reason(self):
        items = [post(GOOD),
                 post(GOOD.replace("good.example", "old.example"), hours=60),
                 post("Hiring Java Developer, Bengaluru, 6+ years. Mail a@six.example"),
                 post("Hiring .NET Developer, Pune, 3 years. Mail a@net.example"),
                 post("Hiring Node.js Developer, Dallas USA W2, 3 years. Mail a@us.example"),
                 post("Hiring Sales Manager, Pune. Mail a@sales.example")]
        result = self.run_with([dict(item, author=f"Recruiter {i}") for i, item in enumerate(items)])
        self.assertEqual(["jobs@good.example"], [lead["contact_email"] for lead in result["leads"]])
        self.assertEqual({"too_old": 1, "experience": 1, "excluded_stack": 1, "location": 1, "role": 2},
                         {k: v for k, v in result["dropped"].items()})

    def test_feed_remote_outside_india_and_off_role_titles_are_dropped(self):
        import_leads(self.ws, "himalayas", [
            {"guid": "p", "companyName": "YO AI Labs", "title": "Japanese Language Expert",
             "locationRestrictions": ["Peru"], "pubDate": NOW.timestamp() - 3600},
            {"guid": "q", "companyName": "Acme", "title": "Backend Engineer", "description": "Node, Redis",
             "locationRestrictions": ["India"], "pubDate": NOW.timestamp() - 3600}])
        result = screen(self.ws, now=NOW)
        self.assertEqual(["Backend Engineer"], [lead["title"] for lead in result["leads"]])
        self.assertEqual({"location": 1, "role": 1}, result["dropped"])

    def test_live_review_regressions(self):
        cases = ["Hiring Java Developer (Female Candidates), Hyderabad, 3-5 years. Mail a@f.example",
                 "Hiring Java Full Stack Developer, Chennai, Experience: 5.1-11 Years. Mail a@d.example",
                 "Hiring Node.js & React Developer, Irving, Texas. OPT welcome. Mail a@t.example",
                 "Hiring Technical Project Manager + Developer, React, remote India. Mail a@p.example",
                 "Senior Security Engineer, GenAI guardrails, Remote India, 4+ years. Mail a@s.example"]
        result = self.run_with([dict(post(c), author=f"R{i}") for i, c in enumerate(cases)])
        self.assertEqual(0, result["kept"])

    def test_high_volume_poster_is_dropped(self):
        spam = [post(f"Hiring React Developer {i}, Pune, 3 years. Mail r{i}@spam.example", author="Spammer")
                for i in range(5)]
        result = self.run_with(spam + [post(GOOD)])
        self.assertEqual(5, result["dropped"]["poster_volume"])
        self.assertEqual(1, result["kept"])

    def test_applied_contact_or_company_domain_is_dropped(self):
        result = self.run_with([post(GOOD)], applied={"@good.example"})
        self.assertEqual((0, 1), (result["kept"], result["dropped"]["applied"]))

    def test_fit_is_explained_and_ranked(self):
        weak = "Hiring Software Engineer, Pune, 3 years. Rust, Elixir, Kotlin. Mail w@weak.example"
        result = self.run_with([post(weak, author="Recruiter B"), post(GOOD)])
        top = result["leads"][0]
        self.assertEqual("jobs@good.example", top["contact_email"])
        self.assertIn("redis", top["matched_skills"])
        self.assertGreater(top["fit"], result["leads"][1]["fit"])
        self.assertEqual(["poster_unverified"], top["checks_pending"])


if __name__ == "__main__":
    unittest.main()
