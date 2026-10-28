# Host-model orchestration

Implemented tasks: draft_cv, draft_letter, review. Extraction, semantic mapping,
repair loops and API-backed execution are not implemented. The CLI never calls a
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
