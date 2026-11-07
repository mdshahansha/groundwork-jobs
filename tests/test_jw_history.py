"""JW-22: history import persistence, mapping, duplicates, repeat-import identity, export round trip
(FR-ONB-06, T-ONB-08)."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from jw.cli import main
from jw.contracts import WorkspaceError, canonical
from jw.csv_archive import normalize_csv
from jw.history import export_history, history, import_history
from jw.workspace import Workspace

CSV = ("Company,Role,Applied,Status,Notes,Notes\r\n"
       "Fixture Co,Platform Engineer,2026-09-01,Interview,via referral,=1+1\r\n"
       "fixture co , platform  engineer,01/09/2026,,dup by date format,\r\n"
       "Other Ltd,Data Engineer,sometime,Rejected,,\r\n"
       ",Missing Co,2026-09-03,,,\r\n"
       "Third,SRE,2026-09-04,ghosted,\"multi\nline\",\r\n").encode("utf-8")
MAPPING = {"company": "Company", "title": "Role", "date": "Applied", "outcome": "Status",
           "date_formats": ["%Y-%m-%d", "%d/%m/%Y"]}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.ws = Workspace(self.root, create=True)
        self.addCleanup(lambda: self.ws.close())

    def assertCode(self, code, call, *args, **kwargs):
        with self.assertRaises(WorkspaceError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def test_import_report_and_rows(self):
        report = import_history(self.ws, CSV, MAPPING)
        self.assertEqual((5, 2, [{"line": 3}]), (report["rows"], report["imported"], report["duplicates"]))
        self.assertEqual([{"line": 4, "reason": "date_not_in_declared_formats"},
                          {"line": 5, "reason": "company_or_title_missing"}], report["invalid"])
        self.assertIn("duplicate_headings_kept_positionally", report["warnings"])
        self.assertIn({"line": 6, "unknown_outcome": True}, report["warnings"])
        rows = {r["line"]: r for r in history(self.ws, report["import_id"])}
        self.assertEqual(("interview", "candidate_confirmed", "2026-09-01", "imported"),
                         (rows[2]["outcome"], rows[2]["outcome_origin"], rows[2]["applied_on"], rows[2]["origin"]))
        self.assertEqual((None, "unknown"), (rows[6]["outcome"], rows[6]["outcome_origin"]))
        self.assertEqual("=1+1", rows[2]["extra"]["Notes"])

    def test_repeat_import_reuses_and_cross_import_duplicates(self):
        first = import_history(self.ws, CSV, MAPPING)
        again = import_history(self.ws, CSV, MAPPING)
        self.assertEqual((first["import_id"], True), (again["import_id"], again["reused"]))
        self.assertEqual(1, self.ws.db.execute("SELECT count(*) FROM history_imports").fetchone()[0])
        more = b"Company,Role,Applied\r\nFIXTURE CO,Platform Engineer,2026-09-01\r\nNew,Role,2026-10-01\r\n"
        second = import_history(self.ws, more, {"company": "Company", "title": "Role", "date": "Applied",
                                                "date_formats": ["%Y-%m-%d"]})
        self.assertEqual((1, [{"line": 2}]), (second["imported"], second["duplicates"]))

    def test_windows_1252_is_detected(self):
        raw = "Company,Role,Applied\r\nCafé Ltd,Engineer,2026-09-01\r\n".encode("cp1252")
        report = import_history(self.ws, raw, {"company": "Company", "title": "Role", "date": "Applied",
                                               "date_formats": ["%Y-%m-%d"]})
        self.assertEqual(("cp1252", 1), (report["encoding"], report["imported"]))
        self.assertEqual("Café Ltd", history(self.ws, report["import_id"])[0]["company"])

    def test_bad_mappings_are_refused_and_nothing_stored(self):
        self.assertCode("mapping_heading", import_history, self.ws, CSV, dict(MAPPING, company="Employer"))
        self.assertCode("mapping_heading", import_history, self.ws, CSV, dict(MAPPING, outcome="Notes"))
        self.assertCode("invalid_schema", import_history, self.ws, CSV, dict(MAPPING, date_formats=[]))
        self.assertCode("invalid_schema", import_history, self.ws, CSV, dict(MAPPING, guess=True))
        self.assertCode("invalid_csv", import_history, self.ws, b"a,b\r\n1\r\n", MAPPING)
        self.assertEqual(0, self.ws.db.execute("SELECT count(*) FROM history_rows").fetchone()[0])

    def test_t_onb_08_round_trip_keeps_original_columns(self):
        report = import_history(self.ws, CSV, MAPPING)
        exported = normalize_csv(export_history(self.ws, report["import_id"]))
        original = normalize_csv(CSV)
        self.assertEqual(original["headings"] + ["jw_status", "jw_line"], exported["headings"])
        width = len(original["headings"])
        for before, after in zip(original["rows"], exported["rows"]):
            inert = [c if not c.startswith("=") else "'" + c for c in before]
            self.assertEqual(inert, after[:width])
        self.assertEqual(["imported", "duplicate", "invalid", "invalid", "imported"],
                         [row[width] for row in exported["rows"]])

    def test_cli_import_show_export(self):
        self.ws.close()
        csv_path = Path(self.temp.name) / "tracker.csv"
        csv_path.write_bytes(CSV)
        out = Path(self.temp.name) / "export.csv"

        def run(command, payload):
            request = Path(self.temp.name) / (command + ".json")
            request.write_text(canonical(payload), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--workspace", str(self.root), command, "--input", str(request)])
            return code, json.loads(output.getvalue())

        code, result = run("history-import", {"path": str(csv_path), "mapping": MAPPING})
        import_id = result["result"]["import_id"]
        self.assertEqual(5, len(run("history-show", {"import_id": import_id})[1]["result"]))
        self.assertEqual(0, run("history-export", {"import_id": import_id, "output_path": str(out)})[0])
        self.assertTrue(out.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(3, run("history-export", {"import_id": import_id, "output_path": str(out)})[0])
        self.ws = Workspace(self.root)


if __name__ == "__main__":
    unittest.main()
