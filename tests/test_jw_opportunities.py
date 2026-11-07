"""JW-21: source posts, layered dedup (T-DED-01..03), reversible merge, keyset pagination and the
prior-application guard (FR-DED-03)."""

from pathlib import Path
import tempfile
import unittest

from jw.contracts import WorkspaceError, canonical
from jw.history import import_history
from jw.opportunities import Opportunities, canonical_url
from jw.tasks import Tasks
from jw.workspace import Workspace

TEXT = "We are hiring a Backend Engineer to build Python services and APIs for payments at scale."


def post(**changes):
    value = {"provider": "linkedin", "company": "Fixture Co", "title": "Backend Engineer", "location": "Berlin",
             "text": TEXT}
    value.update(changes)
    return value


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "workspace", create=True)
        self.addCleanup(lambda: self.ws.close())
        self.opps = Opportunities(self.ws)

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_canonical_url_drops_tracking(self):
        self.assertEqual("https://jobs.example.com/a?id=7",
                         canonical_url("http://WWW.jobs.example.com/a/?utm_source=x&id=7&trk=y#top"))

    def test_t_ded_01_post_and_careers_page_merge_with_both_sources(self):
        a = self.opps.ingest(post(external_id="li-1", url="https://jobs.example.com/be?utm_source=li",
                                  requisition="REQ-9"))
        b = self.opps.ingest(post(provider="careers", url="https://www.jobs.example.com/be/", requisition="REQ-9"))
        self.assertEqual((a["opportunity_id"], 2, "merged"),
                         (b["opportunity_id"], b["merge"]["layer"], b["merge"]["state"]))
        self.assertEqual({"linkedin", "careers"},
                         {s["provider"] for s in self.opps.opportunity(a["opportunity_id"])["sources"]})

    def test_t_ded_02_different_locations_or_requisitions_never_merge(self):
        a = self.opps.ingest(post())
        b = self.opps.ingest(post(location="Pune"))
        self.assertEqual((None, True), (b["merge"], a["opportunity_id"] != b["opportunity_id"]))
        c = self.opps.ingest(post(requisition="R-1", provider="x"))
        d = self.opps.ingest(post(requisition="R-2", provider="y"))
        self.assertNotEqual(c["opportunity_id"], d["opportunity_id"])

    def test_t_ded_03_unmerge_restores_both_opportunities(self):
        a = self.opps.ingest(post(requisition="REQ-1"))
        b = self.opps.ingest(post(provider="careers", requisition="REQ-1"))
        self.assertEqual(3, b["merge"]["layer"])
        self.assertEqual(1, self.opps.unmerge(b["merge"]["merge_id"])["posts_restored"])
        self.assertEqual([a["post_id"]], [s["post_id"] for s in self.opps.opportunity(a["opportunity_id"])["sources"]])
        restored = self.ws.store.one("merges", b["merge"]["merge_id"])["absorbed_id"]
        self.assertEqual([b["post_id"]], [s["post_id"] for s in self.opps.opportunity(restored)["sources"]])
        self.assertCode("merge_not_active", self.opps.unmerge, b["merge"]["merge_id"])

    def test_layers_four_to_six_only_propose(self):
        self.opps.ingest(post(recruiter="jane@fixture.invalid"))
        title_match = self.opps.ingest(post(provider="indeed", text="Totally different words here."))
        self.assertEqual((4, "proposed"), (title_match["merge"]["layer"], title_match["merge"]["state"]))
        recruiter = self.opps.ingest(post(provider="mail", title="Platform Lead", text="Unrelated.",
                                          recruiter="jane@fixture.invalid"))
        self.assertEqual((6, "proposed"), (recruiter["merge"]["layer"], recruiter["merge"]["state"]))
        self.assertEqual("merged", self.opps.decide(title_match["merge"]["merge_id"], True)["state"])
        self.assertCode("merge_not_proposed", self.opps.decide, title_match["merge"]["merge_id"], False)

    def test_same_external_id_is_reused(self):
        first = self.opps.ingest(post(external_id="li-1"))
        again = self.opps.ingest(post(external_id="li-1", text="edited"))
        self.assertEqual((first["post_id"], True), (again["post_id"], again["reused"]))

    def test_keyset_pagination_is_stable_under_inserts(self):
        for i in range(5):
            self.opps.ingest(post(company=f"Co {i}"))
        first = self.opps.page(limit=2)
        self.opps.ingest(post(company="Late Co"))
        seen, page = [i["opportunity_id"] for i in first["items"]], first
        while page["next_cursor"]:
            page = self.opps.page(page["next_cursor"], limit=2)
            seen += [i["opportunity_id"] for i in page["items"]]
        self.assertEqual((6, 6), (len(seen), len(set(seen))))
        self.assertCode("invalid_cursor", self.opps.page, "not-a-cursor")

    def test_prior_application_guard(self):
        text = "Built Python services."
        source = self.ws.import_source(text.encode(), sensitivity="public")["source_id"]
        self.ws.add_claim(source, 0, len(text))
        self.ws.set_profile("Synthetic Candidate", "candidate@example.invalid")
        self.ws.publish_profile()
        import_history(self.ws, b"Company,Role,Applied\r\nfixture co,backend engineer,2026-09-01\r\n",
                       {"company": "Company", "title": "Role", "date": "Applied", "date_formats": ["%Y-%m-%d"]})
        job = self.ws.add_job({"company": "Fixture Co", "title": "Backend Engineer", "description": "D",
                               "requirements": []})["job_id"]
        tasks = Tasks(self.ws)
        self.assertCode("prior_application", tasks.create, job, "draft_cv", consent=True)
        self.assertEqual("needs_model", tasks.create(job, "draft_cv", consent=True, prepare_anyway=True)["state"])


if __name__ == "__main__":
    unittest.main()
