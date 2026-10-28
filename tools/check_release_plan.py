#!/usr/bin/env python3
"""Check JW-01 specification consistency; does not test product runtime behavior."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(prd: str, plan: str, hld: str) -> list[str]:
    errors = []
    declarations = re.findall(r"(?m)^\*\*(FR-[A-Z]+-\d+) (.+)$", prd)
    headers = dict(declarations)
    if len(headers) != len(declarations):
        errors.append("Duplicate FR declaration in PRD")
    required = {key for key, value in declarations if "Must (R1" in value}
    mapped = re.findall(r"(?m)^\| (FR-[A-Z]+-\d+) \| (?:M1[^|]*|R1 completion) \|", plan)
    if not required:
        errors.append("No R1 Must declarations found")
    if len(mapped) != len(set(mapped)):
        errors.append("Duplicate R1 disposition row")
    for key in sorted(required - set(mapped)):
        errors.append(f"Missing R1 disposition: {key}")
    for key in sorted(set(mapped) - required):
        errors.append(f"Disposition is not declared R1 Must: {key}")
    for key in sorted(set(re.findall(r"\bFR-[A-Z]+-\d+", plan)) - set(headers)):
        errors.append(f"Unknown requirement reference: {key}")
    for key in ("FR-CFG-02", "FR-DIS-01", "FR-DIS-02", "FR-DIS-06", "FR-DOC-11", "FR-ANL-01"):
        if key not in required:
            errors.append(f"R1 prerequisite not promoted: {key}")
    if "Could (R3)" not in headers.get("FR-CAP-01", ""):
        errors.append("Quick capture must follow the R3 API")
    contents = prd.split("### 4.2 Release contents", 1)[-1].split("### 4.3", 1)[0]
    rows = {cells[0]: cells for line in contents.splitlines() if line.startswith("| R")
            for cells in [[cell.strip() for cell in line.strip("|").split("|")]]}
    if "CAP" in " ".join(rows.get("R2", [])) or "CAP" not in " ".join(rows.get("R3", [])):
        errors.append("Capability release table contradicts capture timing")
    if "ANL collection" not in " ".join(rows.get("R1", [])):
        errors.append("R1 release table omits telemetry collection")
    if "### 4.2 Release contents" not in prd:
        errors.append("Missing PRD release table")
    for name, text in (("PRD", prd), ("HLD", hld)):
        if "05-release-plan.md" not in text:
            errors.append(f"{name} does not link to the delivery plan")
    if "```mermaid\nflowchart" not in plan:
        errors.append("Missing dependency graph")
    checklist = plan.split("## 6. Ordered first-milestone checklist", 1)[-1].split("## 7.", 1)[0]
    numbers = [int(value) for value in re.findall(r"(?m)^(\d+)\. ", checklist)]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        errors.append("Milestone checklist missing or not sequential")
    scenarios = re.findall(r"(?m)^\| (M1-\d{2}):", plan)
    if scenarios != [f"M1-{number:02}" for number in range(1, 13)]:
        errors.append("Expected unique ordered scenarios M1-01 through M1-12")
    return errors


def main() -> int:
    prd, plan, hld = [
        (ROOT / "docs" / name).read_text(encoding="utf-8")
        for name in ("02-prd.md", "05-release-plan.md", "03-hld.md")
    ]
    errors = check(prd, plan, hld)
    if errors:
        print("\n".join(f"FAIL: {error}" for error in errors))
        return 1
    count = len(re.findall(r"(?m)^\*\*FR-[A-Z]+-\d+[^\n]*Must \(R1", prd))
    print(f"OK: {count} R1 Musts mapped; release assignments, graph and M1 inventory consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
