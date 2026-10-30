"""Disclosure policy fixtures contain only synthetic candidate data."""

from datetime import timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from jw.cli import dispatch
from jw.contracts import WorkspaceError, canonical, instant, utcnow
from jw.privacy import Privacy, PREPARATION
from jw.store import SCHEMA, Store
from jw.tasks import Tasks
from jw.workspace import Workspace


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(self.ws.close)
        self.policy = Privacy(self.ws)
        self.safe_text = "Built Python services."
        self.safe = self.claim(self.safe_text, "public")
        self.secret = self.claim("Salary history SYNTHETIC-90000", "restricted")
        self.ws.set_profile("Synthetic", "fixture@example.invalid")
        self.ws.publish_profile()
        self.job = self.job_create("Fixture")
        self.expiry = (instant(utcnow()) + timedelta(hours=1)).isoformat()

    def claim(self, text, sensitivity):
        source = self.ws.import_source(text.encode(), sensitivity=sensitivity)["source_id"]
        return self.ws.add_claim(source, 0, len(text))["claim_id"]

    def job_create(self, company):
        return self.ws.add_job({"company": company, "title": "Engineer", "description": "Python",
                                "requirements": ["Python"]})["job_id"]

    def grant(self, claim=None, purpose="ats"):
        return self.policy.grant(claim or self.secret, self.job, purpose, "portal-fixture",
                                 self.expiry, True)["consent_id"]

    def preview(self, consent=None, **overrides):
        data = dict(claim_id=self.secret, job_id=self.job, purpose="ats", recipient="portal-fixture",
                    consent_id=consent)
        data.update(overrides)
        return self.policy.preview(**data)

    def test_confirmation_preserves_restriction_rules_and_lineage(self):
        self.policy.set_rule(self.secret, ["ats:manual"])
        consent = self.grant()
        corrected = self.ws.correct_claim(self.secret, "Salary history SYNTHETIC-95000")
        row = self.ws.store.one("claims", corrected["claim_id"])
        self.assertEqual("restricted", row["sensitivity"])
        self.assertEqual("candidate_confirmation", corrected["provenance"])
        self.assertEqual({"ats:manual"}, self.policy.scopes(corrected["claim_id"]))
        self.assertFalse(self.preview(consent)["allowed"])
        self.assertFalse(self.preview(consent, claim_id=corrected["claim_id"])["allowed"])
        self.assertNotIn("SYNTHETIC-95000", canonical(self.ws.evidence()))

    def test_exception_requires_rule_and_exact_application_consent(self):
        with self.assertRaises(WorkspaceError):
            self.grant()
        self.policy.set_rule(self.secret, ["ats:manual", "referral:manual"])
        self.assertFalse(self.preview()["allowed"])
        consent = self.grant()
        self.assertTrue(self.preview(consent)["allowed"])
        for changes in ({"recipient": "other"}, {"job_id": self.job_create("Other")},
                        {"purpose": "referral"}, {"purpose": "cv"}, {"media": "image"}):
            result = self.preview(consent, **changes)
            self.assertFalse(result["allowed"])
            self.assertNotIn("text", result)
        referral = self.grant(purpose="referral")
        self.assertTrue(self.preview(referral, purpose="referral")["allowed"])
        self.assertNotIn("SYNTHETIC-90000", canonical(self.ws.evidence()))

    def test_expiry_revocation_and_rule_change_invalidate(self):
        self.policy.set_rule(self.secret, ["ats:manual"])
        consent = self.grant()
        with patch("jw.privacy.utcnow", return_value=self.expiry):
            self.assertFalse(self.preview(consent)["allowed"])
        self.policy.revoke(consent)
        self.assertFalse(self.preview(consent)["allowed"])
        consent = self.grant()
        self.policy.set_rule(self.secret, ["ats:manual"])
        self.assertFalse(self.preview(consent)["allowed"])

    def test_denial_logs_no_values_and_images_never_reach_review(self):
        self.policy.set_rule(self.secret, ["ats:manual"])
        result = self.preview(self.grant(), media="image")
        self.assertEqual("image_unclassified", result["reason"])
        audit = canonical([dict(row) for row in self.ws.db.execute("SELECT * FROM audit")])
        self.assertNotIn("SYNTHETIC-90000", audit)
        self.assertNotIn("portal-fixture", audit)
        task = Tasks(self.ws).create(self.job, "draft_cv", consent=True)["task_id"]
        self.assertNotIn("SYNTHETIC-90000", canonical(Tasks(self.ws).packet(task)))

    def test_field_policy_excludes_every_preparation_output(self):
        hidden = self.claim("PUBLIC-BUT-NOT-DISCLOSABLE", "public")
        self.policy.set_rule(hidden, ["preparation:local", "preparation:export"])
        self.ws.publish_profile()
        self.assertNotIn("PUBLIC-BUT", canonical(self.ws.dependencies(self.job)))
        result = dispatch(self.ws, "profile-map", {"job_id": self.job, "markdown": "PUBLIC-BUT-NOT-DISCLOSABLE"})
        self.assertEqual([], result["assertions"])
        tasks = Tasks(self.ws)
        ids = []
        for kind in ("draft_cv", "draft_letter"):
            task = tasks.create(self.job, kind, consent=True)["task_id"]
            packet = tasks.packet(task)
            self.assertNotIn("PUBLIC-BUT", canonical(packet))
            tasks.submit(task, canonical({"output": {"assertions": [{"text": self.safe_text, "claim_id": self.safe}]},
                "usage": {"model": "fixture", "input_tokens": None, "output_tokens": None}}).encode())
            self.assertNotIn("PUBLIC-BUT", canonical(tasks.private_export(task)))
            ids.append(task)
        review = tasks.create(self.job, "review", consent=True, draft_id=ids[0])["task_id"]
        self.assertNotIn("PUBLIC-BUT", canonical(tasks.packet(review)))
        path = Path(self.temp.name) / "preview.zip"
        tasks.handoff_preview(*ids, str(path))
        import zipfile
        from pypdf import PdfReader
        with zipfile.ZipFile(path) as archive:
            for name in ("cv.pdf", "letter.pdf"):
                text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(archive.read(name))).pages)
                self.assertNotIn("PUBLIC-BUT", text)
                self.assertNotIn("SYNTHETIC-90000", text)
        self.policy.set_rule(self.safe, [])
        with self.assertRaises(WorkspaceError):
            tasks.private_export(ids[0])

    def test_no_cv_exception_and_no_blanket_consent(self):
        self.policy.set_rule(self.secret, sorted(PREPARATION | {"ats:manual"}))
        self.assertNotIn("SYNTHETIC-90000", canonical(self.ws.evidence()))
        with self.assertRaises(WorkspaceError):
            self.policy.grant(self.secret, self.job, "cv", "recipient", self.expiry, True)
        with self.assertRaises(WorkspaceError):
            self.policy.grant(self.secret, self.job, "ats", "recipient", self.expiry, "yes")

    def test_image_containers_rejected_even_when_labelled_public(self):
        for text in ('<svg><text>ID SYNTHETIC-123</text></svg>', '<img src="fixture">', 'data:image/png;base64,fixture'):
            with self.assertRaises(WorkspaceError):
                self.ws.import_source(text.encode(), sensitivity="public")
        # An old database may already contain textual image markup. Egress
        # must deny it even without a new import.
        source_id = self.ws.store.one("claims", self.safe)["source_id"]
        self.ws.db.execute("UPDATE sources SET text=? WHERE id=?", ('<svg>ID SYNTHETIC-123</svg>', source_id))
        self.assertEqual([], self.ws.evidence())

    def test_extreme_consent_expiry_is_structured_error(self):
        for timestamp in ("9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00"):
            with self.assertRaises(WorkspaceError) as caught:
                self.policy.grant(self.secret, self.job, "ats", "fixture", timestamp, True)
            self.assertEqual("invalid_time", caught.exception.code)


class PrivacyMigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_data_and_reopens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = sqlite3.connect(root / "workspace.sqlite3")
            db.executescript(SCHEMA)
            db.execute("UPDATE profile SET name='Synthetic',email='fixture@example.invalid'")
            db.commit()
            db.close()
            store = Store(root)
            self.assertEqual(4, store.db.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual("Synthetic", store.db.execute("SELECT name FROM profile").fetchone()[0])
            store.close()
            Store(root).close()

    def test_failed_upgrade_rolls_back_without_partial_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = sqlite3.connect(root / "workspace.sqlite3")
            db.executescript(SCHEMA)
            db.close()
            with patch("jw.store.PRIVACY_SCHEMA", ("CREATE TABLE partial (id TEXT)", "INVALID SQL")):
                with self.assertRaises(sqlite3.Error):
                    Store(root)
            db = sqlite3.connect(root / "workspace.sqlite3")
            self.assertEqual(1, db.execute("PRAGMA user_version").fetchone()[0])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())
            db.close()
