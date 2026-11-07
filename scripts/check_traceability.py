#!/usr/bin/env python3
"""Fail on requirement IDs cited in code but missing from the PRD, and on a stale traceability file.

    python3 scripts/check_traceability.py          # check
    python3 scripts/check_traceability.py --write  # regenerate docs/implementation/TRACEABILITY.md
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jw.traceability import dangling, matrix, render  # noqa: E402

TARGET = ROOT / "docs" / "implementation" / "TRACEABILITY.md"


def main(argv):
    bad = dangling()
    if bad:
        print("Cited but not defined in docs/02-prd.md: " + ", ".join(bad))
        return 1
    text = render(matrix())
    if "--write" in argv:
        TARGET.write_text(text, encoding="utf-8")
        print("Wrote " + TARGET.relative_to(ROOT).as_posix())
        return 0
    if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
        print("docs/implementation/TRACEABILITY.md is stale; run with --write.")
        return 1
    print("OK: no dangling requirement IDs; traceability matrix is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
