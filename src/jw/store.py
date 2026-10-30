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
SCHEMA_VERSION = 3


class Store:
    def __init__(self, root, create=False):
        self.root = Path(root).resolve()
        require(not ((CODE_CHECKOUT / ".git").exists() and self.root.is_relative_to(CODE_CHECKOUT)),
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
        require(table in {"sources", "claims", "jobs", "tasks"}, "invalid_schema", "Unknown entity.")
        string(identifier, 100)
        row = self.db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        require(row is not None, "not_found", "Entity not found.")
        return row

    def audit(self, kind, identifier):
        self.db.execute("INSERT INTO audit(kind,entity_id,at) VALUES (?,?,?)",
                        (kind, identifier, utcnow()))

    def close(self):
        self.db.close()
