# SQLite schema and persistence

Schema 2 adds field disclosure rules and application-bound consents through an
additive transaction. See [migration and rollback](DISCLOSURE_POLICY.md).

`workspace.sqlite3` is canonical. Schema 1 is the initial schema in `store.py`.
Creation runs in an exclusive transaction; unsupported schema versions fail.
No deployed older workspace schema is migrated by this checkpoint. Downgrade
and restore are not supported; do not overwrite a live database from a backup.

| Entity | Identity / constraints | Stored contents |
|---|---|---|
| sources | opaque ID, unique SHA-256 identity | raw bytes, decoded text, independent provenance/sensitivity, state |
| source_links | child/parent FK pair, no self-link | correction lineage |
| claims | opaque ID, source FK, unique source/span | exact text, character offsets, sensitivity, state |
| profile | singleton key | corrected name/email, published flag |
| jobs | opaque ID, unique immutable input fingerprint | normalized JSON with honest unknowns |
| tasks | opaque ID, unique fingerprint, job FK | packet, validated output, dependency hash, state, budgets, usage, times |
| policies, active_policy | policy hash | normalised ranking policy; one active (schema 5, JW-07) |
| requirement_reviews | opaque ID; unique job, group, index, claim | host-model mapping verdict and attempts (schema 5) |
| rankings | opaque ID, job FK, policy hash | pinned result, fingerprint, current/outdated (schema 5) |
| extractions | opaque ID, unique fingerprint, source FK | packet, span proposals, state, budgets, usage (schema 6, JW-08) |
| task_sources | task/source FK pair | erasure dependency graph |
| outcomes | opaque ID, unique job/kind/effective time | append-only manual events |
| audit | monotonic sequence | event code, opaque entity ID, timestamp; no source text |
| deletions | source ID | durable-in-current-database deletion marker/time |

SQLite primary/unique constraints supply identity indexes. Foreign keys are
enabled on every connection. All mutating services use `BEGIN IMMEDIATE` with
commit/rollback. Source content and task output live in SQLite to avoid partial
artifact-file writes. WAL plus synchronous FULL is enabled; timeout is 10 seconds.

Logical deletion clears raw/extracted/claim/task content and writes deletion
markers in the same transaction. `secure_delete` and a truncating WAL checkpoint
reduce residual local pages; they do not guarantee erasure from SSDs, snapshots,
concurrent reader WALs, OS backups or external exports. No retention period or
restore-time erasure promise is implemented. These are outstanding JW-04/JW-13
acceptance items, not successes inferred from a tombstone table.
