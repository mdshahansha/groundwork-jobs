"""JW-11: immutable action envelopes and hash-bound approvals (FR-AUT-01, FR-AUT-03, FR-AUT-05).
One test per acceptance case, including T-AUT-01..03. No provider exists, so a passing claim
proves only that the guard would let an executor proceed; nothing is sent."""

from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from jw.actions import Actions
from jw.contracts import WorkspaceError
from jw.workspace import Workspace

EMAIL = {"subject": "Platform Engineer application", "body": "Hello, I am applying for the role."}
CV = b"%PDF-1.4 synthetic cv"
TO = "recruiter@example.invalid"


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())
        text = "Built Python services."
        source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.ws.add_claim(source, 0, len(text))
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        self.actions = Actions(self.ws)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def approved(self, channel="email", destination=TO, content=EMAIL, attachments=(CV,), hours=24):
        self.actions.set_mode(channel, "approve_each_action")
        envelope = self.actions.create_envelope(channel, destination, content, list(attachments))
        return self.actions.approve(envelope["envelope_id"], hours=hours)["authorisation_id"]

    def state(self, auth_id):
        return self.ws.store.one("authorisations", auth_id)["state"]

    def test_every_channel_starts_draft_only_and_refuses_approval(self):
        for channel in ("email", "comment", "ats"):
            self.assertEqual("draft_only", self.actions.mode(channel))
        envelope = self.actions.create_envelope("email", TO, EMAIL, [CV])
        self.assertCode("channel_draft_only", self.actions.approve, envelope["envelope_id"])

    def test_exact_approved_action_is_claimed_once(self):
        auth = self.approved()
        result = self.actions.claim(auth, "email", TO, EMAIL, [CV])
        self.assertEqual(("used", "not_performed"), (result["state"], result["provider_call"]))
        self.assertCode("auth_used", self.actions.claim, auth, "email", TO, EMAIL, [CV])

    def test_t_aut_01_edited_cv_after_approval_is_refused(self):
        auth = self.approved()
        self.assertCode("auth_hash_mismatch", self.actions.claim, auth, "email", TO, EMAIL, [CV + b" edited"])
        self.assertEqual("invalid", self.state(auth))

    def test_edited_body_subject_or_recipient_is_refused(self):
        for change in ({"content": dict(EMAIL, body="Hello, edited.")},
                       {"content": dict(EMAIL, subject="Different subject")},
                       {"destination": "other@example.invalid"}):
            with self.subTest(change=change):
                auth = self.approved()
                args = {"destination": TO, "content": EMAIL, **change}
                self.assertCode("auth_hash_mismatch", self.actions.claim, auth, "email",
                                args["destination"], args["content"], [CV])

    def test_added_or_removed_attachment_is_refused(self):
        for attachments in ([], [CV, b"%PDF extra"]):
            with self.subTest(count=len(attachments)):
                auth = self.approved()
                self.assertCode("auth_hash_mismatch", self.actions.claim, auth, "email", TO, EMAIL, attachments)

    def test_t_aut_02_email_approval_does_not_permit_a_comment(self):
        auth = self.approved()
        self.actions.set_mode("comment", "approve_each_action")
        self.assertCode("auth_hash_mismatch", self.actions.claim, auth, "comment", TO,
                        {"body": EMAIL["body"]}, [CV])

    def test_t_aut_03_revoked_authorisation_is_refused(self):
        auth = self.approved()
        self.actions.revoke(auth)
        self.assertCode("auth_revoked", self.actions.claim, auth, "email", TO, EMAIL, [CV])
        self.assertCode("auth_not_active", self.actions.revoke, auth)

    def test_stop_flag_refuses_and_resume_restores(self):
        auth = self.approved()
        self.actions.stop()
        self.assertCode("stopped", self.actions.claim, auth, "email", TO, EMAIL, [CV])
        self.assertEqual("active", self.state(auth))
        self.actions.resume()
        self.assertEqual("used", self.actions.claim(auth, "email", TO, EMAIL, [CV])["state"])

    def test_expired_authorisation_is_refused_and_stays_expired(self):
        auth = self.approved(hours=1)
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        with patch("jw.actions.utcnow", return_value=later):
            self.assertCode("auth_expired", self.actions.claim, auth, "email", TO, EMAIL, [CV])
        self.assertCode("auth_expired", self.actions.claim, auth, "email", TO, EMAIL, [CV])

    def test_switching_back_to_draft_only_blocks_an_approved_action(self):
        auth = self.approved()
        self.actions.set_mode("email", "draft_only")
        self.assertCode("channel_draft_only", self.actions.claim, auth, "email", TO, EMAIL, [CV])

    def test_profile_change_after_approval_is_refused(self):
        auth = self.approved()
        self.ws.set_profile("Synthetic Candidate", "changed@example.invalid")
        self.ws.publish_profile()
        self.assertCode("auth_hash_mismatch", self.actions.claim, auth, "email", TO, EMAIL, [CV])

    def test_profile_change_before_approval_needs_a_new_envelope(self):
        self.actions.set_mode("email", "approve_each_action")
        envelope = self.actions.create_envelope("email", TO, EMAIL, [CV])
        self.ws.set_profile("Synthetic Candidate", "changed@example.invalid")
        self.ws.publish_profile()
        self.assertCode("auth_hash_mismatch", self.actions.approve, envelope["envelope_id"])

    def test_envelopes_cannot_be_edited_in_place(self):
        envelope = self.actions.create_envelope("email", TO, EMAIL, [CV])
        with self.assertRaises(sqlite3.IntegrityError):
            self.ws.db.execute("UPDATE action_envelopes SET content='{}' WHERE id=?", (envelope["envelope_id"],))
        self.ws.db.rollback()

    def test_approval_window_is_one_hour_to_fourteen_days(self):
        self.actions.set_mode("email", "approve_each_action")
        envelope = self.actions.create_envelope("email", TO, EMAIL, [CV])["envelope_id"]
        for hours in (0, 14 * 24 + 1, 1.5):
            with self.subTest(hours=hours):
                self.assertCode("invalid_schema", self.actions.approve, envelope, hours=hours)
        self.assertEqual("active", self.actions.approve(envelope, hours=14 * 24)["state"])

    def test_campaign_mode_falls_back_to_per_action_approval(self):
        self.actions.set_mode("ats", "authorized_campaign")
        envelope = self.actions.create_envelope("ats", "https://jobs.example.invalid/apply/1",
                                                {"answers": {"Notice period": "30 days"}})
        self.assertEqual("approve_each_action", self.actions.approve(envelope["envelope_id"])["approval"])

    def test_malformed_content_and_channels_are_refused(self):
        self.assertCode("invalid_schema", self.actions.create_envelope, "sms", TO, EMAIL)
        self.assertCode("invalid_schema", self.actions.create_envelope, "email", TO, {"body": "no subject"})
        self.assertCode("invalid_schema", self.actions.create_envelope, "ats", TO, {"answers": {}})
        self.assertCode("invalid_schema", self.actions.create_envelope, "email", TO, EMAIL, ["not bytes"])
        self.assertCode("invalid_schema", self.actions.set_mode, "email", "send_freely")


if __name__ == "__main__":
    unittest.main()
