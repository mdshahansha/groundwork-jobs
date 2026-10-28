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
