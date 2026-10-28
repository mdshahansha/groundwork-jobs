# Data lifecycle and states

1. `source-import` stores exact UTF-8 bytes and decoded text in one transaction.
   Default classification is private. PDF/archive input is rejected.
2. `claim-add` selects exact source spans. Claims cannot weaken source sensitivity.
   `claim-correct` creates a versioned confirmation source and supersedes the old claim.
3. `profile-set` records candidate-approved name/email; `profile-publish` checks
   contacts, evidence and conflicts. Contacts are explicitly part of every model packet.
4. `job-add` stores an immutable pasted job snapshot. It always reports
   `credibility=unassessed`, `availability=unverified`, `recommendation=review`.
5. `task-create` materializes a bounded CV/letter or isolated reviewer packet.
   `task-packet` returns it for explicit host use. No model request occurs automatically.
6. `task-submit` accepts supported structured assertions or bounded review findings.
   Completed tasks persist. They are not completed documents or passed quality gates.
7. `draft-export` returns private JSON text plus claim map with `ready=false`.
   It does not create an employer package or update an application outcome.
8. `outcome-record` appends an idempotent, explicitly manual event. There is no
   inferred submission confirmation or outcome projection reducer yet.

Task states: `needs_model` can become `completed`, `blocked_schema`,
`blocked_timeout`, `blocked_quota`, `blocked_rate_limit` or `blocked_refusal`.
Only quota/rate-limit blocks resume while both attempt budget and deadline permit.
Completed work is reused, not rerun. Erasure sets affected tasks to `erased` and
removes packets and results. Input changes deny access with `stale_input` or
`profile_unpublished`; they do not mutate historical outputs into fresh ones.

Correction lineage participates in source deletion. Logical erasure atomically
clears all descendant source/claim content and all dependent task packets/results.
External copies are outside this transaction and cannot be recalled. Backup
restore is disabled pending an independent durable erasure/recovery boundary.
