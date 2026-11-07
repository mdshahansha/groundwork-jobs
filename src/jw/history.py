"""JW-22: tracker history import (FR-ONB-06) on top of the strict CSV utilities.

- Original bytes, encoding and heading order are stored; rows keep their line numbers.
- Encoding is UTF-8 (with or without BOM) or Windows-1252, declared or detected in that order.
- A mapping names the heading for company, title, date and optionally outcome; date formats are
  declared, never guessed. Unknown columns stay in `extra`.
- Outcomes are `candidate_confirmed` only when the CSV states a known one; otherwise `unknown`.
- Duplicates (company + title + date, case- and space-insensitive) are reported, not imported,
  within a file and across earlier imports. The same bytes imported again reuse the first import.
- Invalid rows are reported with line numbers; valid rows still import.
- Export keeps the original columns in their order and appends `jw_status` and `jw_line`.
"""

from datetime import datetime
import json

from .contracts import canonical, digest, require, utcnow
from .csv_archive import archive_identity, export_safe_csv, normalize_csv

FIELDS = ("company", "title", "date", "outcome")
OUTCOMES = {"applied": "manual_applied", "interview": "interview", "offer": "offer", "rejected": "rejected",
            "withdrawn": "withdrawn"}
ENCODINGS = ("utf-8-sig", "cp1252")


def _mapping(mapping, headings):
    require(isinstance(mapping, dict), "invalid_schema", "Mapping must be an object.")
    allowed = set(FIELDS) | {"date_formats", "encoding"}
    require(set(mapping) <= allowed and {"company", "title", "date", "date_formats"} <= set(mapping),
            "invalid_schema", "Mapping needs company, title, date and date_formats; outcome and encoding optional.")
    for field in FIELDS:
        if field in mapping:
            require(isinstance(mapping[field], str) and headings.count(mapping[field]) == 1, "mapping_heading",
                    "Mapped heading for " + field + " must appear exactly once in the CSV.")
    formats = mapping["date_formats"]
    require(isinstance(formats, list) and 0 < len(formats) <= 10 and
            all(isinstance(f, str) and f.count("%") >= 2 for f in formats), "invalid_schema",
            "date_formats is a list of strptime formats.")
    return {field: headings.index(mapping[field]) for field in FIELDS if field in mapping}


def _decode(raw, encoding):
    require(encoding in ("auto",) + ENCODINGS, "invalid_schema", "Encoding is auto, utf-8-sig or cp1252.")
    last = None
    for codec in (ENCODINGS if encoding == "auto" else (encoding,)):
        try:
            return normalize_csv(raw, codec)
        except ValueError as exc:
            last = exc
    require(False, "invalid_csv", str(last))


def _date(value, formats):
    for form in formats:
        try:
            return datetime.strptime(value.strip(), form).date().isoformat()
        except ValueError:
            continue
    return None


def _key(text):
    return " ".join(text.split()).casefold()


def import_history(ws, raw, mapping):
    require(isinstance(raw, bytes) and raw, "invalid_schema", "CSV bytes are required.")
    sha = archive_identity(raw)
    existing = ws.db.execute("SELECT id, report FROM history_imports WHERE sha256=?", (sha,)).fetchone()
    if existing:
        return dict(json.loads(existing["report"]), import_id=existing["id"], reused=True)
    from .workspace import identifier

    table = _decode(raw, mapping.get("encoding", "auto") if isinstance(mapping, dict) else "auto")
    headings = table["headings"]
    columns = _mapping(mapping, headings)
    mapped = set(columns.values())
    report = {"rows": len(table["rows"]), "imported": 0, "duplicates": [], "invalid": [], "warnings": [],
              "encoding": table["encoding"], "sha256": sha}
    if len(set(headings)) != len(headings):
        report["warnings"].append("duplicate_headings_kept_positionally")
    with ws.store.transaction():
        import_id = identifier("hist")
        seen = {r[0] for r in ws.db.execute("SELECT identity FROM history_rows WHERE status='imported'")}
        rows = []
        for line, cells in enumerate(table["rows"], start=2):
            company, title = cells[columns["company"]].strip(), cells[columns["title"]].strip()
            applied = _date(cells[columns["date"]], mapping["date_formats"])
            stated = cells[columns["outcome"]].strip().casefold() if "outcome" in columns else ""
            outcome = OUTCOMES.get(stated)
            extra = {headings[i]: cells[i] for i in range(len(cells)) if i not in mapped}
            status, identity, reason = "imported", None, None
            if not company or not title:
                status, reason = "invalid", "company_or_title_missing"
            elif applied is None:
                status, reason = "invalid", "date_not_in_declared_formats"
            else:
                identity = digest([_key(company), _key(title), applied])
                if identity in seen:
                    status, reason = "duplicate", "company_title_date"
                else:
                    seen.add(identity)
            if status == "invalid":
                report["invalid"].append({"line": line, "reason": reason})
            elif status == "duplicate":
                report["duplicates"].append({"line": line})
            else:
                report["imported"] += 1
            if stated and outcome is None:
                report["warnings"].append({"line": line, "unknown_outcome": True})
            rows.append((identifier("hrow"), import_id, line, canonical(cells), status,
                         company or None, title or None, applied, outcome,
                         "candidate_confirmed" if outcome else "unknown", canonical(extra),
                         identity if status == "imported" else None, reason))
        ws.db.execute("INSERT INTO history_imports VALUES (?,?,?,?,?,?,?,?)",
                      (import_id, sha, table["encoding"], canonical(headings), canonical(mapping), raw,
                       canonical(report), utcnow()))
        ws.db.executemany("INSERT INTO history_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        ws.store.audit("history_imported", import_id)
    return dict(report, import_id=import_id, reused=False)


def history(ws, import_id):
    ws.store.one("history_imports", import_id)
    return [{"line": r["line"], "status": r["status"], "company": r["company"], "title": r["title"],
             "applied_on": r["applied_on"], "outcome": r["outcome"], "outcome_origin": r["outcome_origin"],
             "origin": "imported", "extra": json.loads(r["extra"]), "reason": r["reason"]}
            for r in ws.db.execute("SELECT * FROM history_rows WHERE import_id=? ORDER BY line", (import_id,))]


def export_history(ws, import_id):
    """Original columns in original order, then appended jw_status and jw_line. Formula cells are made inert."""
    row = ws.store.one("history_imports", import_id)
    headings = json.loads(row["headings"])
    rows = [json.loads(r["cells"]) + [r["status"], str(r["line"])] for r in ws.db.execute(
        "SELECT cells, status, line FROM history_rows WHERE import_id=? ORDER BY line", (import_id,))]
    return export_safe_csv({"headings": headings + ["jw_status", "jw_line"], "rows": rows})
