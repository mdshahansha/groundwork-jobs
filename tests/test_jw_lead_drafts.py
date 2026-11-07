"""Lead pipeline phase 3: a draft is ready only when every claim, figure and technology is supported."""

from pathlib import Path
import tempfile
import unittest

from jw.lead_drafts import check, drafts, packet, submit
from jw.leads import import_leads
from jw.workspace import Workspace

FACTS = ("Synthetic Candidate. Full Stack Engineer, about 3 years. Node.js, TypeScript, React.js, PostgreSQL, Redis. "
         "Redis caching cut authorization checks from 80 ms to under 1 ms.")
POST = {"title": "Node.js Developer", "text": "Hiring Node.js Developer in Pune, 2-4 years. Mail jobs@good.example",
        "contact_email": "jobs@good.example"}
SUBJECT = "Application: Node.js Developer - Synthetic Candidate"
BODY = ("Hello,\n\nI am applying for the Node.js Developer role in Pune. I have about 3 years of full stack work "
        "with Node.js, TypeScript and PostgreSQL.\n\nAt my current team, Redis caching I added cut authorization "
        "checks from 80 ms to under 1 ms.\n\nMy resume is attached. I would welcome a conversation.\n\n"
        "Regards,\nSynthetic Candidate")


class DraftCheckTests(unittest.TestCase):
    def run_check(self, subject=SUBJECT, body=BODY, post=POST):
        return check(post, subject, body, FACTS, "Synthetic Candidate")

    def test_supported_draft_passes(self):
        self.assertEqual([], self.run_check()["failed"])

    def test_invented_figure_and_unsupported_skill_block(self):
        risk = self.run_check(body=BODY.replace("80 ms", "95% faster at 80 ms") + "\nI also run Kafka clusters.")
        self.assertEqual(["unsupported_numbers", "unsupported_skills"], risk["failed"])
        self.assertIn("kafka", risk["details"]["unsupported_skills"])

    def test_compensation_only_when_post_asks(self):
        body = BODY + "\nCurrent CTC 8 LPA, notice period 15 days."
        self.assertIn("compensation", self.run_check(body=body)["failed"])
        asked = dict(POST, text=POST["text"] + " Share current CTC and notice period.")
        risk = check(asked, SUBJECT, body, FACTS + " 8 LPA 15 days", "Synthetic Candidate")
        self.assertNotIn("compensation", risk["failed"])

    def test_tone_subject_resume_and_contact(self):
        risk = self.run_check(subject="Urgent application", body=BODY.replace("My resume is attached.", "")
                              + "\nI am passionate and a team player. Please consider me for one chance.")
        self.assertEqual(["banned_phrases", "resume", "subject"], risk["failed"])
        self.assertIn("no_contact", self.run_check(post=dict(POST, contact_email=None))["failed"])

    def test_personal_data_request_is_flagged_not_blocked(self):
        risk = self.run_check(post=dict(POST, text=POST["text"] + " Share DOB and PAN card."))
        self.assertEqual(["dob", "pan card"], risk["post_asks_personal_data"])
        self.assertEqual([], risk["failed"])


class DraftStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ws = Workspace(Path(temp.name) / "ws", create=True)
        self.addCleanup(self.ws.close)
        self.facts = Path(temp.name) / "facts.md"
        self.facts.write_text(FACTS, encoding="utf-8")
        self.post_id = import_leads(self.ws, "linkedin_posts", [{"text": POST["text"]}])["posts"][0]["post_id"]

    def test_packet_submit_and_resubmit_discards_previous(self):
        self.assertIn("Never invent", packet(self.ws, self.post_id, self.facts)["standard"])
        first = submit(self.ws, self.post_id, SUBJECT, BODY + "\nI led Kafka.", self.facts, "Synthetic Candidate")
        self.assertEqual("blocked", first["state"])
        second = submit(self.ws, self.post_id, SUBJECT, BODY, self.facts, "Synthetic Candidate")
        self.assertEqual("ready", second["state"])
        self.assertEqual(["discarded", "ready"], [d["state"] for d in drafts(self.ws)])


if __name__ == "__main__":
    unittest.main()
