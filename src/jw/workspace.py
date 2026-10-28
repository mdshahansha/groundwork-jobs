"""Local application services. Imported content has no execution authority."""

import hashlib
import json
import re
import uuid

from .contracts import (MAX_BYTES, PROVENANCE, SENSITIVITY, VERSIONS, canonical,
                        digest, fields, require, string, utcnow, instant)
from .store import Store


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex


def disclosable(source, claim):
    """One conservative policy for packets, drafts, reviews and exports."""
    return (source["state"] == "active" and claim["state"] == "active"
            and source["sensitivity"] == claim["sensitivity"] == "public")


class Workspace:
    def __init__(self, root, create=False):
        self.store = Store(root, create=create)
        self.db = self.store.db

    def close(self):
        self.store.close()

    def import_source(self, raw, provenance="document", sensitivity="private"):
        require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES,
                "input_too_large", "Source must contain 1..1000000 bytes.")
        require(isinstance(provenance, str) and isinstance(sensitivity, str)
                and provenance in PROVENANCE and sensitivity in SENSITIVITY,
                "invalid_schema", "Unknown provenance or sensitivity.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            require(False, "unsupported_format", "Only UTF-8 text sources are supported.")
        require("\x00" not in text and not raw.startswith((b"%PDF", b"PK\x03\x04")),
                "unsupported_format", "PDFs and archives require a qualified parser.")
        string(text, MAX_BYTES)
        sha = hashlib.sha256(raw).hexdigest()
        with self.store.transaction():
            existing = self.db.execute("SELECT * FROM sources WHERE sha256=?", (sha,)).fetchone()
            if existing:
                require(existing["state"] == "active", "source_deleted",
                        "This source was erased; automatic reimport is blocked.")
                require((existing["provenance"], existing["sensitivity"]) == (provenance, sensitivity),
                        "classification_conflict", "Identical source already has immutable classification.")
                return {"source_id": existing["id"], "reused": True}
            source_id = identifier("src")
            self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                            (source_id, sha, raw, text, provenance, sensitivity, "active", utcnow()))
            self.store.audit("source_imported", source_id)
        return {"source_id": source_id, "reused": False}

    def add_claim(self, source_id, start, end, sensitivity=None, state="active"):
        with self.store.transaction():
            source = self.store.one("sources", source_id)
            require(source["state"] == "active", "source_deleted", "Source is not active.")
            require(type(start) is int and type(end) is int and 0 <= start < end <= len(source["text"]),
                    "invalid_span", "Offsets must bound a non-empty source excerpt.")
            require(end - start <= 2000, "input_too_large", "Claim excerpt exceeds 2000 characters.")
            sensitivity = sensitivity or source["sensitivity"]
            levels = {"public": 0, "private": 1, "restricted": 2}
            require(isinstance(sensitivity, str) and sensitivity in levels
                    and levels[sensitivity] >= levels[source["sensitivity"]],
                    "policy_denied", "Claims cannot weaken source sensitivity.")
            require(state in ("active", "conflict"), "invalid_schema", "Invalid initial claim state.")
            existing = self.db.execute("SELECT * FROM claims WHERE source_id=? AND start=? AND end=?",
                                       (source_id, start, end)).fetchone()
            if existing:
                require(existing["sensitivity"] == sensitivity and existing["state"] == state,
                        "classification_conflict", "Existing claim classification differs.")
                return {"claim_id": existing["id"], "reused": True}
            claim_id = identifier("clm")
            self.db.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?)",
                            (claim_id, source_id, source["text"][start:end], start, end, sensitivity, state))
            self.db.execute("UPDATE profile SET published=0")
            self.store.audit("claim_added", claim_id)
        return {"claim_id": claim_id, "reused": False}

    def correct_claim(self, claim_id, text):
        """A correction is a new source, not mutation or declassification of the old one."""
        string(text)
        with self.store.transaction():
            old = self.store.one("claims", claim_id)
            source = self.store.one("sources", old["source_id"])
            require(source["state"] == "active" and old["state"] in {"active", "conflict"},
                    "claim_inactive", "Only current claims can be corrected.")
            # Include the old ID in content identity so distinct confirmations do not collide.
            source_id, new_id = identifier("src"), identifier("clm")
            sha = digest({"corrects": claim_id, "text": text})
            self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
                            (source_id, sha, text.encode(), text, "candidate_confirmation",
                             old["sensitivity"], "active", utcnow()))
            self.db.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?)",
                            (new_id, source_id, text, 0, len(text), old["sensitivity"], "active"))
            self.db.execute("INSERT INTO source_links VALUES (?,?)", (source_id, old["source_id"]))
            self.db.execute("UPDATE claims SET state='superseded' WHERE id=?", (claim_id,))
            self.db.execute("UPDATE profile SET published=0")
            self.store.audit("claim_corrected", claim_id)
        return {"claim_id": new_id, "source_id": source_id, "provenance": "candidate_confirmation",
                "sensitivity": old["sensitivity"]}

    def set_profile(self, name, email):
        string(name, 120)
        require("\n" not in name and "\t" not in name, "invalid_schema", "Name must be one line.")
        require(isinstance(email, str) and len(email) <= 254 and
                re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email),
                "invalid_schema", "Provide a single email address.")
        with self.store.transaction():
            self.db.execute("UPDATE profile SET name=?,email=?,published=0", (name, email))
            self.store.audit("profile_corrected", "profile")
        return {"state": "unpublished"}

    def publish_profile(self):
        with self.store.transaction():
            profile = self.db.execute("SELECT * FROM profile").fetchone()
            require(profile["name"] and profile["email"], "profile_incomplete", "Name and email are required.")
            require(not self.db.execute("SELECT 1 FROM claims WHERE state='conflict'").fetchone(),
                    "profile_conflict", "Resolve conflicting claims before publishing.")
            require(bool(self.evidence()), "profile_incomplete", "At least one public active claim is required.")
            self.db.execute("UPDATE profile SET published=1")
            self.store.audit("profile_published", "profile")
        return {"state": "published", "warning": "Source support is not independent verification."}

    def evidence(self):
        claims = self.db.execute("SELECT * FROM claims ORDER BY id").fetchall()
        return [{"claim_id": c["id"], "source_id": c["source_id"], "text": c["text"],
                 "provenance": s["provenance"], "sensitivity": c["sensitivity"]}
                for c in claims for s in [self.store.one("sources", c["source_id"])]
                if disclosable(s, c)]

    def add_job(self, data):
        fields(data, {"company", "title", "description", "requirements"}, {"requisition"})
        for key in ("company", "title"):
            string(data[key], 200)
        string(data["description"], 20000)
        if "requisition" in data:
            string(data["requisition"], 200)
        require(isinstance(data["requirements"], list) and len(data["requirements"]) <= 100,
                "invalid_schema", "Requirements must be a list of at most 100 strings.")
        for value in data["requirements"]:
            string(value, 500)
        normalized = dict(data, credibility="unassessed", availability="unverified",
                          recommendation="review")
        fingerprint = digest(normalized)
        with self.store.transaction():
            old = self.db.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
            if old:
                return {"job_id": old["id"], "reused": True, "credibility": "unassessed"}
            job_id = identifier("job")
            self.db.execute("INSERT INTO jobs VALUES (?,?,?)", (job_id, fingerprint, canonical(normalized)))
            self.store.audit("job_imported", job_id)
        return {"job_id": job_id, "reused": False, "credibility": "unassessed"}

    def dependencies(self, job_id):
        profile = dict(self.db.execute("SELECT * FROM profile").fetchone())
        require(profile.pop("published") == 1, "profile_unpublished", "Publish the corrected profile first.")
        profile.pop("singleton")
        return {"profile": profile, "evidence": self.evidence(),
                "job": json.loads(self.store.one("jobs", job_id)["data"]),
                "versions": VERSIONS, "calculation_date": utcnow()[:10]}

    def deletion_preview(self, source_id):
        self.store.one("sources", source_id)
        descendants = self._descendants(source_id)
        counts = {}
        for table, column in (("claims", "source_id"), ("task_sources", "source_id")):
            counts[table] = sum(self.db.execute(f"SELECT count(*) FROM {table} WHERE {column}=?",
                                               (item,)).fetchone()[0] for item in descendants)
        return {"source_id": source_id, "copies": counts,
                "source_ids": descendants,
                "erased": ["raw", "extracted_text", "claim_text", "dependent_packets_and_outputs"],
                "retained": ["opaque_ids", "hashes", "audit_timestamps", "deletion_marker"],
                "limitations": "External exports, filesystem snapshots and backups are not recalled. Restore is disabled."}

    def _descendants(self, source_id):
        return [row[0] for row in self.db.execute(
            "WITH RECURSIVE affected(id) AS (SELECT id FROM sources WHERE id=? UNION "
            "SELECT child_id FROM source_links JOIN affected ON parent_id=affected.id) "
            "SELECT id FROM affected ORDER BY id", (source_id,))]

    def delete_source(self, source_id):
        with self.store.transaction():
            preview = self.deletion_preview(source_id)
            for item in preview["source_ids"]:
                self.db.execute("UPDATE sources SET raw=NULL,text='',state='deleted' WHERE id=?", (item,))
                self.db.execute("UPDATE claims SET text='',state='revoked' WHERE source_id=?", (item,))
                self.db.execute("UPDATE tasks SET packet=NULL,output=NULL,state='erased' WHERE id IN "
                                "(SELECT task_id FROM task_sources WHERE source_id=?)", (item,))
                self.db.execute("INSERT OR IGNORE INTO deletions VALUES (?,?)", (item, utcnow()))
            self.db.execute("UPDATE profile SET published=0")
            self.store.audit("source_deleted", source_id)
        # Physical-media erasure is not guaranteed (WAL/readers, snapshots, SSDs).
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return dict(preview, state="logically_erased")

    def record_outcome(self, job_id, kind, effective_at):
        require(kind in ("prepared", "manual_applied", "interview", "offer", "rejected", "withdrawn"),
                "invalid_schema", "Unsupported manual outcome.")
        effective_at = instant(effective_at).isoformat()
        require(instant(effective_at) <= instant(utcnow()), "invalid_time", "Outcome cannot be future-dated.")
        with self.store.transaction():
            self.store.one("jobs", job_id)
            existing = self.db.execute("SELECT id FROM outcomes WHERE job_id=? AND kind=? AND effective_at=?",
                                       (job_id, kind, effective_at)).fetchone()
            outcome_id = existing["id"] if existing else identifier("evt")
            self.db.execute("INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?)",
                            (outcome_id, job_id, kind, effective_at, utcnow(), "manual"))
            if not existing:
                self.store.audit("manual_outcome", outcome_id)
        return {"outcome_id": outcome_id, "source": "manual", "provider_confirmed": False}

    def rank(self, job_id, mapping, assessment):
        from .ranking import score

        with self.store.transaction():
            dependencies = self.dependencies(job_id)
            requirements = dependencies["job"]["requirements"]
            require(isinstance(mapping, list) and len(mapping) == len(requirements),
                    "invalid_schema", "Provide exactly one mapping for every stored requirement.")
            evidence = {c["claim_id"]: c for c in dependencies["evidence"]}
            states, matrix = {}, []
            for item in mapping:
                fields(item, {"index", "state", "claim_id"})
                index, state, claim_id = item["index"], item["state"], item["claim_id"]
                require(type(index) is int and 0 <= index < len(requirements) and index not in states,
                        "invalid_schema", "Requirement index is duplicate or out of range.")
                require(state in ("supported", "partial", "unsupported", "unknown"),
                        "invalid_schema", "Unknown mapping state; hard constraints cannot be not_applicable.")
                if state in ("supported", "partial"):
                    string(claim_id, 100)
                    require(claim_id in evidence, "unknown_claim", "Mapping requires current public evidence.")
                    if state == "supported":
                        phrase = re.escape(requirements[index].casefold())
                        require(re.search(r"(?<!\w)" + phrase + r"(?!\w)", evidence[claim_id]["text"].casefold()) is not None,
                                "unsupported_mapping", "Direct lexical support is absent; use partial or unknown.")
                else:
                    require(claim_id is None, "invalid_schema", "Unknown/unsupported mappings cannot cite a claim.")
                states[index] = state
                matrix.append(dict(item, requirement=requirements[index],
                                   evidence_label="related" if state == "partial" else "candidate_assessed"))
            result = score([states[i] for i in range(len(requirements))], [], assessment, utcnow()[:10])
            result.update(job_id=job_id, requirement_matrix=sorted(matrix, key=lambda item: item["index"]),
                          dependency_fingerprint=digest(dependencies),
                          ranking_fingerprint=digest({"dependencies": dependencies, "mapping": sorted(matrix, key=lambda item: item["index"]),
                                                      "assessment": assessment, "calculation": "calculations@1"}),
                          assessment_origin="candidate_supplied_not_semantically_verified")
            return result

    def status(self):
        return {"schema_version": 1, "profile_published": bool(self.db.execute(
                    "SELECT published FROM profile").fetchone()[0]),
                "tasks": [dict(row) for row in self.db.execute(
                    "SELECT id,kind,state,attempts,deadline FROM tasks ORDER BY created_at,id")],
                "capabilities": {"text_sources": "available", "host_tasks": "available", "ranking": "candidate_assessed",
                    "ready_export": "blocked_toolchain_and_quality", "pdf_import": "unsupported",
                    "send": "unsupported", "ats": "unsupported", "capture_api": "unsupported",
                    "restore": "unsupported", "scheduler": "unsupported"}}
