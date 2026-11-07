"""SQLite is canonical; blobs and metadata commit together, not across files."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .contracts import require, string, utcnow

SCHEMA = """
CREATE TABLE sources (
 id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, raw BLOB,
 text TEXT NOT NULL, provenance TEXT NOT NULL CHECK(provenance IN ('document','candidate_confirmation')),
 sensitivity TEXT NOT NULL CHECK(sensitivity IN ('public','private','restricted')),
 state TEXT NOT NULL CHECK(state IN ('active','deleted')), created_at TEXT NOT NULL);
CREATE TABLE claims (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 text TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
 sensitivity TEXT NOT NULL CHECK(sensitivity IN ('public','private','restricted')),
 state TEXT NOT NULL CHECK(state IN ('active','superseded','conflict','revoked')),
 UNIQUE(source_id,start,end));
CREATE TABLE source_links (
 child_id TEXT NOT NULL REFERENCES sources(id), parent_id TEXT NOT NULL REFERENCES sources(id),
 PRIMARY KEY(child_id,parent_id), CHECK(child_id != parent_id));
CREATE TABLE profile (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), name TEXT NOT NULL,
 email TEXT NOT NULL, published INTEGER NOT NULL CHECK(published IN (0,1)));
INSERT INTO profile VALUES (1,'','',0);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, data TEXT NOT NULL);
CREATE TABLE tasks (
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES jobs(id), packet TEXT, output TEXT,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL, deadline TEXT NOT NULL, dependency TEXT NOT NULL,
 created_at TEXT NOT NULL, completed_at TEXT, usage TEXT);
CREATE TABLE task_sources (
 task_id TEXT NOT NULL REFERENCES tasks(id), source_id TEXT NOT NULL REFERENCES sources(id),
 PRIMARY KEY(task_id,source_id));
CREATE TABLE outcomes (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 kind TEXT NOT NULL, effective_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='manual'), UNIQUE(job_id,kind,effective_at));
CREATE TABLE audit (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 entity_id TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE deletions (source_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL);
PRAGMA user_version=1;
"""


# Protect this application checkout, not a whole home with a dotfiles repository.
CODE_CHECKOUT = Path(__file__).resolve().parents[2]

PRIVACY_SCHEMA = (
    "CREATE TABLE disclosure_rules (claim_id TEXT PRIMARY KEY REFERENCES claims(id), scopes TEXT NOT NULL)",
    "CREATE TABLE disclosure_consents (id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id), "
    "job_id TEXT NOT NULL REFERENCES jobs(id), purpose TEXT NOT NULL, recipient TEXT NOT NULL, "
    "expires_at TEXT NOT NULL, binding TEXT NOT NULL, revoked INTEGER NOT NULL CHECK(revoked IN (0,1)))",
)

# Candidate-approved rewordings of one claim. Never a new fact source: the claim stays the evidence.
SEMANTIC_SCHEMA = (
    "CREATE TABLE paraphrases (id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id), "
    "text TEXT NOT NULL, guard TEXT NOT NULL, acknowledged TEXT NOT NULL, approved_at TEXT NOT NULL, "
    "revoked INTEGER NOT NULL CHECK(revoked IN (0,1)), UNIQUE(claim_id, text))",
)
# A paraphrase reaches evidence only after an independent host-model entailment review.
# Rows approved under schema 3 default to needs_model: they fail closed until reviewed.
REVIEW_SCHEMA = (
    "ALTER TABLE paraphrases ADD COLUMN review TEXT NOT NULL DEFAULT 'needs_model'",
    "ALTER TABLE paraphrases ADD COLUMN review_attempts INTEGER NOT NULL DEFAULT 0",
)
# JW-07: immutable ranking policies, host-model requirement reviews and pinned rankings.
RANKING_SCHEMA = (
    "CREATE TABLE policies (hash TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE active_policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "hash TEXT NOT NULL REFERENCES policies(hash), activated_at TEXT NOT NULL)",
    "CREATE TABLE requirement_reviews (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), "
    "grp TEXT NOT NULL CHECK(grp IN ('required','preferred')), idx INTEGER NOT NULL, "
    "claim_id TEXT NOT NULL REFERENCES claims(id), review TEXT NOT NULL, "
    "review_attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, UNIQUE(job_id,grp,idx,claim_id))",
    "CREATE TABLE rankings (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), "
    "policy_hash TEXT NOT NULL REFERENCES policies(hash), ranking_fingerprint TEXT NOT NULL, "
    "result TEXT NOT NULL, created_at TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('current','outdated')))",
)
# JW-08: source-scoped claim extraction proposals. Not job tasks: a source has no job.
EXTRACTION_SCHEMA = (
    "CREATE TABLE extractions (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, "
    "source_id TEXT NOT NULL REFERENCES sources(id), packet TEXT, output TEXT, state TEXT NOT NULL, "
    "attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL, deadline TEXT NOT NULL, "
    "created_at TEXT NOT NULL, completed_at TEXT, usage TEXT)",
)
# JW-09: mechanical gate runs on rendered bytes, keyed by draft task and PDF hash.
VERIFICATION_SCHEMA = (
    "CREATE TABLE verifications (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), "
    "pdf_sha256 TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL)",
)
# JW-11: channel modes, frozen action envelopes, hash-bound authorisations and the stop flag.
ACTION_SCHEMA = (
    "CREATE TABLE channel_modes (channel TEXT PRIMARY KEY CHECK(channel IN ('email','comment','ats')), "
    "mode TEXT NOT NULL CHECK(mode IN ('draft_only','approve_each_action','authorized_campaign')), updated_at TEXT NOT NULL)",
    "CREATE TABLE action_envelopes (id TEXT PRIMARY KEY, channel TEXT NOT NULL, action_type TEXT NOT NULL, "
    "destination TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, attachment_hashes TEXT NOT NULL, "
    "profile_version TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TRIGGER action_envelopes_immutable BEFORE UPDATE ON action_envelopes "
    "BEGIN SELECT RAISE(ABORT, 'action envelopes are immutable'); END",
    "CREATE TABLE authorisations (id TEXT PRIMARY KEY, envelope_id TEXT NOT NULL REFERENCES action_envelopes(id), "
    "channel TEXT NOT NULL, action_type TEXT NOT NULL, destination TEXT NOT NULL, content_hash TEXT NOT NULL, "
    "attachment_hashes TEXT NOT NULL, profile_version TEXT NOT NULL, expires_at TEXT NOT NULL, creator TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('active','used','expired','revoked','invalid')), created_at TEXT NOT NULL, "
    "ended_at TEXT)",
    "CREATE TABLE controls (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
# JW-12: one fenced execution lease and the attempt recorded before every provider call.
EXECUTION_SCHEMA = (
    "CREATE TABLE leases (name TEXT PRIMARY KEY, holder TEXT NOT NULL, token INTEGER NOT NULL, "
    "expires_at TEXT NOT NULL)",
    "CREATE TABLE attempts (id TEXT PRIMARY KEY, authorisation_id TEXT NOT NULL UNIQUE REFERENCES authorisations(id), "
    "channel TEXT NOT NULL, destination TEXT NOT NULL, lease_token INTEGER NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('in_flight','accepted','failed','unknown')), provider_ref TEXT, "
    "evidence TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
)
# JW-20: an envelope may name the job it acts for, so the reducer can place its attempts.
RUN_SCHEMA = ("ALTER TABLE action_envelopes ADD COLUMN job_id TEXT REFERENCES jobs(id)",)
# JW-22: imported tracker history, kept with its original bytes and row order.
HISTORY_SCHEMA = (
    "CREATE TABLE history_imports (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, encoding TEXT NOT NULL, "
    "headings TEXT NOT NULL, mapping TEXT NOT NULL, raw BLOB NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE history_rows (id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES history_imports(id), "
    "line INTEGER NOT NULL, cells TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('imported','duplicate','invalid')), "
    "company TEXT, title TEXT, applied_on TEXT, outcome TEXT, outcome_origin TEXT, extra TEXT NOT NULL, "
    "identity TEXT, reason TEXT, UNIQUE(import_id, line))",
    "CREATE INDEX history_identity ON history_rows(identity) WHERE status='imported'",
)
# JW-13: permanent suppression list (hashes only); company '' means every company.
SUPPRESSION_SCHEMA = (
    "CREATE TABLE suppressions (address_sha256 TEXT NOT NULL, company TEXT NOT NULL, reason TEXT NOT NULL, "
    "at TEXT NOT NULL, PRIMARY KEY(address_sha256, company))",
    "CREATE TRIGGER suppressions_permanent BEFORE DELETE ON suppressions "
    "BEGIN SELECT RAISE(ABORT, 'suppressions are permanent'); END",
)
# JW-15: follow-ups scheduled from an accepted e-mail; one row per follow-up, one-way states.
FOLLOWUP_SCHEMA = (
    "CREATE TABLE followups (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id), "
    "job_id TEXT REFERENCES jobs(id), destination TEXT NOT NULL, seq INTEGER NOT NULL, due_at TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('scheduled','reserved','cancelled')), reason TEXT, "
    "action_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(attempt_id, seq))",
)
# JW-14: mailbox sync. Events hold hashes, a bounded excerpt and the match signals, never the body.
MAIL_SCHEMA = (
    "CREATE TABLE mail_checkpoint (singleton INTEGER PRIMARY KEY CHECK(singleton=1), history_id INTEGER NOT NULL, "
    "updated_at TEXT NOT NULL)",
    "CREATE TABLE mail_events (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, history_id INTEGER NOT NULL, "
    "sender_sha256 TEXT NOT NULL, sender_domain TEXT NOT NULL, subject_sha256 TEXT NOT NULL, excerpt TEXT NOT NULL, "
    "classification TEXT NOT NULL, confidence REAL NOT NULL, job_id TEXT REFERENCES jobs(id), attempt_id TEXT, "
    "signals TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('attached','review','dismissed','not_job_related','ignored')), "
    "received_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE mail_ignored_senders (sender_sha256 TEXT PRIMARY KEY, at TEXT NOT NULL)",
)
# JW-21: every sighting of a job is a source post; opportunities group them through reversible merges.
OPPORTUNITY_SCHEMA = (
    "CREATE TABLE opportunities (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)",
    "CREATE TABLE source_posts (id TEXT PRIMARY KEY, provider TEXT NOT NULL, external_id TEXT, "
    "canonical_url TEXT, company_key TEXT NOT NULL, title_key TEXT NOT NULL, location_key TEXT NOT NULL, "
    "requisition TEXT, recruiter TEXT, shingles TEXT NOT NULL, data TEXT NOT NULL, "
    "origin_opportunity TEXT NOT NULL REFERENCES opportunities(id), "
    "opportunity_id TEXT NOT NULL REFERENCES opportunities(id), job_id TEXT REFERENCES jobs(id), "
    "created_at TEXT NOT NULL, UNIQUE(provider, external_id))",
    "CREATE TABLE merges (id TEXT PRIMARY KEY, into_id TEXT NOT NULL REFERENCES opportunities(id), "
    "absorbed_id TEXT NOT NULL REFERENCES opportunities(id), layer INTEGER NOT NULL, confidence REAL NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('proposed','merged','rejected','undone')), created_at TEXT NOT NULL, "
    "updated_at TEXT NOT NULL)",
)
# JW-19: candidate activity events, for active versus elapsed time with idle gaps excluded.
ACTIVITY_SCHEMA = (
    "CREATE TABLE activity (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id), "
    "run_id TEXT, event TEXT NOT NULL, at TEXT NOT NULL)",
)
SCHEMA_VERSION = 16


class Store:
    def __init__(self, root, create=False):
        self.root = Path(root).resolve()
        # Resolve both sides: a checkout reached through a symlink (macOS /var -> /private/var) must still match.
        checkout = Path(CODE_CHECKOUT).resolve()
        require(not ((checkout / ".git").exists() and self.root.is_relative_to(checkout)),
                "unsafe_workspace", "Store candidate data outside the application source checkout.")
        database = self.root / "workspace.sqlite3"
        require(create or database.is_file(), "not_initialized", "Run init first.")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        try:
            if version == 0 and create:
                # An exclusive transaction prevents competing initializers.
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 0:
                    # executescript commits implicitly: execute individual fixed statements instead.
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            self.db.execute(statement)
                self.db.execute("COMMIT")
                version = 1
            if version == 1:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 1:
                    for statement in PRIVACY_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=2")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 2:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 2:
                    for statement in SEMANTIC_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=3")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 3:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 3:
                    for statement in REVIEW_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=4")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 4:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 4:
                    for statement in RANKING_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=5")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 5:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 5:
                    for statement in EXTRACTION_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=6")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 6:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 6:
                    for statement in VERIFICATION_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=7")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 7:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 7:
                    for statement in ACTION_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=8")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 8:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 8:
                    for statement in EXECUTION_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=9")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 9:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 9:
                    for statement in RUN_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=10")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 10:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 10:
                    for statement in HISTORY_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=11")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 11:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 11:
                    for statement in SUPPRESSION_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=12")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 12:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 12:
                    for statement in FOLLOWUP_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=13")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 13:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 13:
                    for statement in MAIL_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=14")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 14:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 14:
                    for statement in OPPORTUNITY_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=15")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version == 15:
                self.db.execute("BEGIN EXCLUSIVE")
                if self.db.execute("PRAGMA user_version").fetchone()[0] == 15:
                    for statement in ACTIVITY_SCHEMA:
                        self.db.execute(statement)
                    self.db.execute("PRAGMA user_version=16")
                self.db.commit()
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
            require(version == SCHEMA_VERSION, "unsupported_schema", "Workspace schema is unsupported.")
        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def one(self, table, identifier):
        # Only internal callers select a fixed table name.
        require(table in {"sources", "claims", "jobs", "tasks", "requirement_reviews", "rankings", "extractions",
                           "action_envelopes", "authorisations", "attempts", "history_imports", "followups", "merges", "opportunities"}, "invalid_schema", "Unknown entity.")
        string(identifier, 100)
        row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        require(row is not None, "not_found", "Entity not found.")
        return row

    def audit(self, kind, identifier):
        self.db.execute("INSERT INTO audit(kind,entity_id,at) VALUES (?,?,?)",
                        (kind, identifier, utcnow()))

    def close(self):
        self.db.close()
