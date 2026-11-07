"""JW-13: suppression list and the durable recovery boundary for it (FR-EML-04).

An opt-out, a hard bounce or a "wrong person" reply blocks an address permanently (wrong person:
for that company only). Like deletions, suppressions are journaled outside the database, so
restoring an older backup cannot unblock an address; restore and backup rotation re-apply the
journal. Only a SHA-256 of the normalised address is stored, in the table and in the journal.
"""

import hashlib
import json
import os
from pathlib import Path

from .contracts import require, string, utcnow

JOURNAL = "suppression-journal.jsonl"
REASONS = ("opt_out", "hard_bounce", "wrong_recipient", "candidate_request")


def address_key(address):
    string(address, 320)
    normal = address.strip().casefold()
    require("@" in normal and " " not in normal, "invalid_schema", "Expected an e-mail address.")
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def company_key(company):
    return "" if company is None else " ".join(str(company).split()).casefold()


def journal(root):
    path = Path(root) / JOURNAL
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(root, entry):
    with (Path(root) / JOURNAL).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def suppress(ws, address, reason, company=None):
    require(reason in REASONS, "invalid_schema", "Reason is opt_out, hard_bounce, wrong_recipient or candidate_request.")
    require((reason == "wrong_recipient") == (company is not None), "invalid_schema",
            "wrong_recipient needs the company; other reasons block the address everywhere.")
    entry = {"address_sha256": address_key(address), "company": company_key(company), "reason": reason,
             "at": utcnow()}
    _insert(ws, entry)
    _append(ws.store.root, entry)
    return {"suppressed": True, "scope": "company" if company else "all", "reason": reason}


def _insert(ws, entry):
    with ws.store.transaction():
        ws.db.execute("INSERT OR IGNORE INTO suppressions VALUES (?,?,?,?)",
                      (entry["address_sha256"], entry["company"], entry["reason"], entry["at"]))
        ws.store.audit("address_suppressed", entry["address_sha256"][:16])


def apply_journal(ws, entries):
    """Re-insert every journaled suppression the database lacks. Returns how many were missing."""
    missing = 0
    for entry in entries:
        if not ws.db.execute("SELECT 1 FROM suppressions WHERE address_sha256=? AND company=?",
                             (entry["address_sha256"], entry["company"])).fetchone():
            _insert(ws, entry)
            missing += 1
    return missing


def suppressed(ws, address, company=None):
    key = address_key(address)
    return ws.db.execute("SELECT reason FROM suppressions WHERE address_sha256=? AND company IN ('',?)",
                         (key, company_key(company))).fetchone() is not None
