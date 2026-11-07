"""JW-24: requirement IDs cited in code exist in the PRD; command contracts have JSON Schemas."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from jw.cli import COMMANDS, main
from jw.traceability import citations, command_schemas, dangling, defined, matrix, render

# Built at runtime so this file does not itself cite IDs the PRD lacks.
FAKE = "FR-" + "ZZZ-99"
BARE = "FR-" + "PRV-03"


class TraceabilityTests(unittest.TestCase):
    def test_no_dangling_requirement_ids(self):
        self.assertEqual([], dangling())

    def test_prd_ids_are_found(self):
        ids = defined()
        for expected in ("FR-AUT-01", "NFR-PRV-03", "T-AUT-01", "T-ONB-08"):
            self.assertIn(expected, ids)
        self.assertGreater(len(ids), 150)

    def test_dangling_detection_catches_an_invented_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("src/jw", "tests"):
                (root / folder).mkdir(parents=True)
            (root / "tests" / "test_x.py").write_text(f'"""Covers FR-AUT-01 and {FAKE}."""\n', encoding="utf-8")
            self.assertEqual([FAKE], dangling(root=root))
            self.assertEqual({"FR-AUT-01", FAKE}, set(citations(root)))

    def test_nfr_is_not_read_as_fr(self):
        self.assertNotIn(BARE, citations())

    def test_matrix_renders_every_id(self):
        rows = matrix()
        text = render(rows)
        self.assertEqual(len(defined()), len(rows))
        self.assertIn("| T-AUT-01 |", text)
        self.assertIn("tests/test_jw_actions.py", next(r for r in rows if r["id"] == "T-AUT-01")["tests"])

    def test_every_command_has_a_closed_schema(self):
        schemas = command_schemas()
        self.assertEqual(set(COMMANDS), set(schemas))
        for name, schema in schemas.items():
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(set(schema["required"]) <= set(schema["properties"]))
        self.assertEqual(["confirm", "source_id"], schemas["source-delete"]["required"])

    def test_cli_schema_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ws"
            with redirect_stdout(io.StringIO()):
                main(["--workspace", str(root), "init"])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--workspace", str(root), "schema"]))
            self.assertIn("resume", json.loads(output.getvalue())["result"])


if __name__ == "__main__":
    unittest.main()
