# Implementation decisions

## D-01: Add the runtime without replacing the LinkedIn bundle

The configured remote is `mdshahansha/groundwork-jobs`. Add `src/jw` as an
independently packaged Python application in this repository. Keep `lib/` and
the 12 plugin skills unchanged. Existing HLD remains the target architecture.
Runtime documentation describes verified subsets, not replacement requirements.

## D-02: Local-first host tasks

Use Python standard-library SQLite with WAL and explicit transactions. The
first runner emits bounded, versioned JSON packets; a host submits results.
There is no implicit network access, model tool authority or provider adapter.
Missing pricing is unknown. No claim of tested live AI/provider performance.

## D-03: Fail closed on unavailable document gates

Plain UTF-8 source import and structured draft creation are the initial path.
PDF/DOCX parsing, sandboxed LaTeX, visual review and ready employer packaging
remain blocked until implemented and verified. Private draft export is not
ready export, submission, or an application outcome. This is an incremental
checkpoint, not an approved reduction of full R1 acceptance.

## D-04: Conservative support and disclosure

Source provenance and sensitivity are separate fields. Candidate confirmation
does not declassify data. Restricted and private claims never enter model
packets. Initial factual support accepts exact excerpts; human-confirmed
paraphrase sources are explicit, not independent employment verification.
Semantic paraphrase evaluation remains outstanding.

## D-05: Publication scope

Publish only synthetic fixtures, runtime source and implementation docs. The
private review backlog and source PDF remain ignored/untracked. This application
checkpoint does not alter LinkedIn skill behavior. Repository-required patch
versioning and release metadata are handled at publication time.

## D-06: Approved fixed-template backend, no Docker

On 2026-10-29 the product owner approved a fixed-template PDF backend and asked
for implementation, commit and push. Initial document builds use pinned
ReportLab with literal text only. No LaTeX/custom template execution, external
images/fonts, or Docker. This explicitly supersedes the renderer choice in the
target HLD for the first slice. Latin-only glyph support and one-page overflow
rejection are exposed limits. Full factual/privacy/review gates remain required.
See ../architecture/FIXED_RENDERER.md for the qualified path and measured evidence.

## D-07: Integration probe disposition and explicit no-send choice

On 2026-10-29 the owner prioritized the four remaining integration checks, then
explicitly chose to skip live Gmail sending. Offline evidence must not be promoted
to live provider proof. Profile storage mapping is separate from Distilly host
inference. Private handoff packaging is separate from verified submission.
Publora POSTs now make one attempt: an idempotency header without a qualified
provider guarantee does not justify retry after an ambiguous response. This
intentional safety change also applies to the shared LinkedIn write client.
See JW02_PROBE_RESULTS.md for executed cases and open acceptance conditions.

## D-08: Restricted fields never enter CV preparation

On 2026-10-29 the owner explicitly chose to keep restricted fields out of CVs.
Per-application ATS/referral manual previews are the only supported exceptions,
requiring both field rules and matching expiring consent. Reusable answers and
candidate confirmation never substitute for consent. Source images are denied
until a qualified image privacy path exists. See
../architecture/DISCLOSURE_POLICY.md for schemas, commands and migration.
