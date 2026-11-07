"""Lead intake: source parsers to JW-21 source posts, with layered dedup on re-import."""

from pathlib import Path
import tempfile
import unittest

from jw.leads import (import_leads, parse_himalayas, parse_linkedin_post, parse_naukri_invite, parse_remoteok,
                      years)
from jw.workspace import Workspace

HTML = (Path(__file__).resolve().parent / "fixtures" / "leads" / "naukri_invite.html").read_text(encoding="utf-8")
INVITE = {"message_id": "m1", "subject": "✉️ Job | Java Full Stack Developer in Gurugram",
          "from": "recruiter@naukri.example", "html": HTML, "received_at": "2026-11-06T10:38:02+00:00"}
POST = {"text": "🚀 We're Hiring | Node.js Developer 📍 Pune 💼 Experience: 2–4 Years. Share resumes at "
                "talent@fixture.example", "url": "https://www.linkedin.com/posts/x_hiring-activity-7524000000000000001-ab",
        "author": "Fixture Recruiter", "posted_at": "2026-11-07T08:00:00+00:00"}


class LeadParserTests(unittest.TestCase):
    def test_years(self):
        self.assertEqual((3, 6), years("3 - 6 years"))
        self.assertEqual((4, None), years("Experience: 4+ Years"))
        self.assertEqual((None, None), years("no requirement stated"))

    def test_naukri_invite(self):
        post = parse_naukri_invite(INVITE)
        self.assertEqual(("naukri", "Fixture Labs Private Limited", "Java Full Stack Developer", "Gurugram"),
                         (post["provider"], post["company"], post["title"], post["location"]))
        self.assertEqual(("900000000001", 3, 6), (post["external_id"], post["min_years"], post["max_years"]))
        self.assertIn("Spring Boot services", post["text"])
        self.assertIn("React.js", post["skills"])

    def test_naukri_non_invite_mail_is_not_a_lead(self):
        self.assertIsNone(parse_naukri_invite(dict(INVITE, subject="You applied for 13 jobs on 05 Nov")))
        self.assertIsNone(parse_naukri_invite(dict(INVITE, html="<p>Show your Javascript expertise</p>")))

    def test_linkedin_post_needs_contact_email(self):
        post = parse_linkedin_post(POST)
        self.assertEqual(("Node.js Developer", "Pune", "talent@fixture.example", "fixture", (2, 4)),
                         (post["title"], post["location"], post["contact_email"], post["company"],
                          (post["min_years"], post["max_years"])))
        self.assertEqual("7524000000000000001", post["external_id"])
        self.assertIsNone(parse_linkedin_post(dict(POST, text="We're hiring, apply on our site")))

    def test_public_feeds(self):
        h = parse_himalayas({"guid": "g1", "companyName": "Acme", "title": "Backend Engineer",
                             "description": "<p>3+ years Node.js</p>", "locationRestrictions": ["India"],
                             "pubDate": 1793961482, "applicationLink": "https://acme.example/apply"})
        self.assertEqual(("Remote (India)", 3), (h["location"], h["min_years"]))
        self.assertIsNone(parse_remoteok({"legal": "notice"}))
        r = parse_remoteok({"id": 7, "position": "React Developer", "company": "Beta", "tags": ["react"],
                            "url": "https://remoteok.example/7", "date": "2026-11-07T00:00:00+00:00"})
        self.assertEqual(("remoteok", "7", "react"), (r["provider"], r["external_id"], r["skills"]))


class LeadImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "ws", create=True)
        self.addCleanup(self.ws.close)

    def test_import_is_idempotent_and_counts_unparsed(self):
        items = [INVITE, dict(INVITE, subject="Naukri digest"), "not an object"]
        first = import_leads(self.ws, "naukri_mail", items)
        self.assertEqual((3, 2, 1, 0), (first["seen"], first["unparsed"], first["new"], first["reused"]))
        again = import_leads(self.ws, "naukri_mail", [INVITE])
        self.assertEqual((0, 1), (again["new"], again["reused"]))
        self.assertEqual(first["posts"][0]["opportunity_id"], again["posts"][0]["opportunity_id"])

    def test_repost_with_same_contact_and_role_is_reused(self):
        a = import_leads(self.ws, "linkedin_posts", [POST])["posts"][0]
        b = import_leads(self.ws, "linkedin_posts", [dict(POST, url=None)])
        self.assertEqual(a["opportunity_id"], b["posts"][0]["opportunity_id"])
        self.assertEqual((1, 0), (b["reused"], b["new"]))

    def test_unknown_source_refused(self):
        from jw.contracts import WorkspaceError
        with self.assertRaises(WorkspaceError):
            import_leads(self.ws, "scrape_anything", [])


if __name__ == "__main__":
    unittest.main()
