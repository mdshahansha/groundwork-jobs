# Host-model orchestration

Implemented tasks: draft_cv, draft_letter, review, repair (JW-08), extract_claims
(JW-08) and requirement mapping review (JW-07). API-backed execution is not
implemented. The CLI never calls a
model or grants tools. Every packet has `allowed_tools=[]`, an untrusted job-data
field, selected public evidence, corrected contacts and version metadata.

Task creation requires explicit consent. The caller must inspect the returned
packet before sharing it with the configured host. Public classification is an
explicit user choice, not automatic declassification of a sensitive source.
Images and whole source documents cannot enter the reviewer packet.

Budgets are fixed checkpoint limits: 64,000 packet/result bytes, 4,096 reported
output tokens, three submission/failure attempts, 24-hour packet lifetime and
12 materialized tasks per job. There is no automatic budget reset. Token usage
can be unknown; cost is always explicitly unknown. This process cannot meter,
cancel or limit host-side calls performed outside it. Candidate-configurable run
budgets, verified model pins and measured active time remain unfinished.

Validation happens outside the model. Output has a closed schema and only known
claim IDs. Each assertion must exactly equal eligible claim text. Extra tool
requests, rationale or fabricated compound assertions are rejected. Invalid
output consumes an attempt but is never stored as canonical output. Minimal
failure audit events contain no raw model response or hidden reasoning.

Review creates a fresh packet containing the accepted draft, evidence, profile,
job and policy metadata, without drafter conversation/rationale. Review findings
have bounded severity codes and assertion indices. Reviewer effectiveness has
not been measured against a held-out corpus. Even an empty findings list cannot
make a draft ready. Rendering, visual review, full gate orchestration and bounded
repairs remain release blockers.

## Repair (FR-DOC-07, JW-08)

`task-create` with `kind=repair` takes a completed review's ID as `draft_id`. Its
packet carries the reviewed draft, the critical and major findings only, the
document kind and the iteration. Output uses the draft schema plus one rule:
every assertion no blocking finding names must survive unchanged and in order
(`repair_out_of_scope` otherwise); named ones may be replaced or removed, and
replacements pass the same exact-claim or entailed-paraphrase check. A repair is
a draft: it can be reviewed, exported privately and rendered. A minor-only
review returns `no_blocking_findings` (the loop ends). After three repairs, a
further request returns `state=blocked_quality`, `ready=false` and the remaining
findings; it never creates a task. Re-running render and visual checks after a
repair is still manual.

## Claim extraction (extract_claims@1, JW-08)

`extraction-create` (explicit consent) is source-scoped, not job-scoped. Only an
active public source qualifies, because the packet holds the whole source text;
a source over the 64,000-byte packet budget is refused. Output is
`{"claims": [{"start", "end", "text"}]}`: 1..100 sorted, non-overlapping spans of
at most 2000 characters whose `text` must equal the source at those offsets
(`evidence_mismatch` otherwise, FR-PRF-03). Proposals never become claims on
their own: `extraction-accept` with explicit `confirm` and chosen indices adds
them through the normal claim path. Deleting the source erases the packet and
output. Same attempt, deadline and output-token limits as job tasks.

## Metering

`usage-report` (`job_id`) lists each task's kind, state, attempts and reported
model and tokens, plus totals. Tokens a host did not report are counted as
unknown, never as zero; cost is always `unknown`. Only completed submissions carry
usage; rejected attempts and host calls outside this process are not metered.
