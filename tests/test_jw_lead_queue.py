"""Lead pipeline phase 4: batch approval, one send per draft, header-only action ID, safe unknowns."""

from pathlib import Path
import tempfile
import unittest

from jw.gmail import DemoGmail
from jw.lead_drafts import submit
from jw.lead_queue import approve, reconcile, send
from jw.leads import import_leads
from jw.workspace import Workspace

FACTS = "Synthetic Candidate. Full stack, about 3 years. Node.js, TypeScript, PostgreSQL."
BODY = ("Hello,\n\nI am applying for the Node.js Developer role. I have about 3 years of full stack work with "
        "Node.js and PostgreSQL.\n\nMy resume is attached.\n\nRegards,\nSynthetic Candidate")


class LeadQueueTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.ws = Workspace(root / "ws", create=True)
        self.addCleanup(self.ws.close)
        text = "Built Node.js services."
        source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.ws.add_claim(source, 0, len(text))
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.facts = root / "facts.md"
        self.facts.write_text(FACTS, encoding="utf-8")
        self.resume = root / "resume.pdf"
        self.resume.write_bytes(b"%PDF-1.4 synthetic resume")
        self.drafts = []
        for i in range(2):
            post = import_leads(self.ws, "linkedin_posts", [{"text": f"Hiring Node.js Developer {i}, Pune, 3 years. "
                                                                     f"Mail jobs{i}@lead.example"}])
            self.drafts.append(submit(self.ws, post["posts"][0]["post_id"],
                                      "Application: Node.js Developer - Synthetic Candidate", BODY, self.facts,
                                      "Synthetic Candidate")["draft_id"])
        self.gmail = DemoGmail(scopes=("gmail.send", "gmail.readonly"))

    def test_batch_sends_once_with_resume_and_hidden_action_id(self):
        approved = approve(self.ws, self.drafts, self.resume)
        self.assertEqual(2, len(approved["approved"]))
        self.assertEqual({d: "already_approved" for d in self.drafts},
                         approve(self.ws, self.drafts, self.resume)["skipped"])
        result = send(self.ws, self.gmail, self.resume, sleep=lambda s: None)
        self.assertEqual(2, result["sent"])
        self.assertEqual(0, send(self.ws, self.gmail, self.resume, sleep=lambda s: None)["sent"])
        self.assertEqual(2, self.gmail.calls.count("send"))
        raw = self.gmail.sent_raw[0]
        self.assertIn("X-JW-Action-Id: act_", raw)
        self.assertIn('filename="resume.pdf"', raw)
        body = raw.split("Content-Disposition: attachment")[0]
        self.assertEqual(1, body.count("act_"))  # header only, not in the visible text

    def test_lost_response_is_unknown_never_resent_then_reconciled(self):
        approve(self.ws, self.drafts[:1], self.resume)
        self.gmail.send_fault = "timeout"
        first = send(self.ws, self.gmail, self.resume, sleep=lambda s: None)
        self.assertEqual("send_unknown", first["results"][0]["state"])
        self.gmail.send_fault = None
        self.assertEqual([], send(self.ws, self.gmail, self.resume, sleep=lambda s: None)["results"])
        self.assertEqual(1, self.gmail.calls.count("send"))
        self.assertEqual("sent_accepted", reconcile(self.ws, self.gmail)["reconciled"][0]["state"])

    def test_changed_resume_is_refused(self):
        approve(self.ws, self.drafts[:1], self.resume)
        self.resume.write_bytes(b"%PDF-1.4 a different resume")
        result = send(self.ws, self.gmail, self.resume, sleep=lambda s: None)
        self.assertEqual("refused", result["results"][0]["state"])
        self.assertEqual(0, self.gmail.calls.count("send"))

    def test_blocked_draft_is_not_approved(self):
        post = import_leads(self.ws, "linkedin_posts", [{"text": "Hiring Node.js Developer, Pune. Mail x@y.example"}])
        blocked = submit(self.ws, post["posts"][0]["post_id"], "Hi", BODY + " Kafka.", self.facts,
                         "Synthetic Candidate")["draft_id"]
        self.assertEqual({blocked: "not_ready"}, approve(self.ws, [blocked], self.resume)["skipped"])


if __name__ == "__main__":
    unittest.main()
