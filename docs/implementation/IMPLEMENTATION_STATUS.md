# Job workspace implementation status

Checkpoint: 2026-10-28. **Partial implementation, not M1 or R1 completion.**
The pre-implementation audit found JW-01 planning complete, JW-24 specification
checks partial, and no job-workspace runtime. Legacy LinkedIn tooling is separate.

Paths are repository-relative. W = tests/test_jw_workspace.py;
C = tests/test_jw_csv_archive.py. Passing subsets do not complete a ticket.

| Ticket | Implementation status | Files changed | Acceptance tests | Evidence | Blockers |
|---|---|---|---|---|---|
| JW-01 | Implemented and verified (planning only) | Existing docs/02-prd.md, docs/03-hld.md, docs/05-release-plan.md | tools/check_release_plan.py | 63 Must dispositions pass | Runtime release gates separate |
| JW-02 | Partially implemented | src/jw/integrations.py; src/jw/tasks.py; lib/publora_client.py; tools/probe_distilly_profile.py; docs/implementation/JW02_PROBE_RESULTS.md | Integration contracts, actual wrapper fallbacks, no-retry POSTs, private ZIP and pinned profile writer probe | Offline contracts and Distilly storage mapping pass; no Docker; live sending skipped by owner | Actual Distilly host inference, durable Gmail sync/recovery and live provider qualification remain open |
| JW-03 | Implemented and verified for supported runtime paths | src/jw/privacy.py; workspace.py; store.py; cli.py; docs/architecture/DISCLOSURE_POLICY.md | tests/test_jw_privacy.py plus existing packet/export privacy tests | Independent provenance/sensitivity, field rules, scoped consent, image denial, migration and owner-approved no-CV-exception policy | Image disclosure remains explicitly denied; provider execution and full document gates are separate tickets |
| JW-04 | Implemented and verified for supported runtime paths | src/jw/workspace.py, store.py, backup.py, cli.py | W.test_deletion_erases_all_dependent_packet_text; test_delete_follows_correction_lineage; test_failed_delete_rolls_back_whole_transaction; tests/test_jw_backup.py (9 tests) | Atomic logical erasure includes descendants; an append-only deletion journal (IDs and hashes only) lives beside the database; `backup` snapshots with a manifest hash and 7 daily / 4 weekly retention, and each rotation re-applies the journal to kept backups; `restore` validates hash and schema, migrates forward, re-applies the journal, turns in-flight attempts into `*_unknown` and sets the stop flag | Physical-media erasure (SSD, filesystem snapshots, external copies) is not guaranteed; artifacts and config are not yet in backups because none are stored outside the database |
| JW-05 | Implemented and verified for supported runtime paths | src/jw/semantics.py, workspace.py, tasks.py, store.py, cli.py; docs/architecture/SEMANTIC_CHECKS.md | tests/test_jw_semantics.py (25 tests); tests/fixtures/jw_paraphrase_corpus.json; W.test_factual_invention_unknown_reference_and_retry_cap | Exact text or a paraphrase passing guard-2, candidate approval and a host-model entailed verdict; 168-row labelled corpus: 120/120 fact changes caught, 0/48 false rejects | Host-model review quality is not measured against real model output; guard is lexical |
| JW-06 | Implemented and verified for supported runtime paths | src/jw/tasks.py, workspace.py, cli.py | W.test_contact_edit_invalidates_pending_and_completed_outputs; test_version_and_calculation_date_invalidate; test_concurrent_identical_requests_have_one_logical_task; tests/test_jw_refresh.py (7 tests) | Immutable fingerprints; eight concurrent requests converge; `model-pin` puts the host model into every dependency fingerprint and refuses output from any other model (`model_mismatch`); `rankings-refresh` re-ranks from recorded inputs when dependencies, policy or calculation date change, and leaves a ranking outdated with its error code when it cannot be rebuilt | Research stays `unavailable` (no network fetcher); templates are the fixed private ones from JW-09; the host's model name is self-reported, not attested |
| JW-07 | Implemented and verified for supported runtime paths | src/jw/policy.py, ranking.py, workspace.py, store.py, cli.py; docs/architecture/SCORING.md | tests/test_jw_policy.py (23 tests); tests/test_jw_ranking.py; W.test_rank_checks_current_claims_and_hard_location | Hashed ranking-policy@1 with path errors and suggestions; outdated marking on change; seven reachable FR-RNK-01 codes with rule and value; preferred requirements; host-model direct/related mapping review; threshold recommendation and gaps | Product approval of provisional formulas; weights@0, calibration and stretch roles; CREDIBILITY_BLOCKED unreachable until a credibility engine; mapping review quality not measured on real model output |
| JW-08 | Implemented and verified for supported runtime paths | src/jw/tasks.py, contracts.py, store.py, workspace.py, cli.py; docs/architecture/AI_ORCHESTRATION.md | tests/test_jw_model_tasks.py (10 tests); W.test_model_output_does_not_gain_tool_authority; test_quota_resume_keeps_prior_draft_and_budget | Closed draft/review/repair/extraction/mapping schemas; repair keeps unnamed assertions and stops at 3 with blocked_quality; extraction spans must equal the source and need candidate acceptance; usage report keeps unknown tokens apart from zero | Host-side calls cannot be metered or cancelled; cost stays unknown; no API runner; candidate-configurable run budgets |
| JW-09 | Implemented and verified for mechanical gates 1-2 | src/jw/verification.py, rendering.py, tasks.py, store.py, workspace.py, cli.py; docs/architecture/FIXED_RENDERER.md | tests/test_jw_verification.py (10 tests); tests/test_jw_rendering.py; workspace privacy and staleness | Gate 1 and 2 checks read the rendered bytes; each check is proven to fail on a drawn defect; required-format workflow blocks unsupported formats; runs stored with PDF hash | Model visual review of page images not run; multilingual fonts; multi-page templates |
| JW-10 | Implemented and verified for supported runtime paths | src/jw/tasks.py | tests/test_jw_review.py (15 tests); W.test_isolated_review_cannot_assert_readiness | Review packet holds only FR-DOC-06 inputs: draft, rendered PDF text and mechanical status, cited evidence, requirement matrix with accepted mappings, policy and style guide; findings carry severity, code, location, claim IDs, correction and blocking flag; policy severity floor per code is enforced | Page images not supplied (no rasteriser); model review quality, held-out corpus and recall not measured on real model output |
| JW-11 | Implemented and verified for supported runtime paths | src/jw/actions.py, store.py (schema 8) | tests/test_jw_actions.py (16 tests, including T-AUT-01..03) | Channels default to draft_only; envelopes are frozen (an UPDATE trigger aborts); approvals bind channel, action type, destination, content hash, attachment hashes and profile version for 1 hour to 14 days; claim recomputes every hash and is single use; stop flag, revoke, expiry and draft_only refuse with stable codes and no provider call | No provider or executor exists; campaign authorisation (FR-AUT-02), review screen (FR-AUT-04) and caps/allowed hours (FR-AUT-06) remain open |
| JW-12 | Implemented and verified for supported runtime paths | src/jw/execution.py, actions.py, store.py (schema 9) | tests/test_jw_execution.py (12 tests: crash after accept, timeout, two workers, fencing) | One executor lease with a monotonic fencing token; an attempt with its action ID (`X-JW-Action-Id`) is recorded and the authorisation spent in one transaction before any provider call; a superseded token's writes are rejected; in-flight attempts from an older lease become `*_unknown`; an unknown attempt blocks its channel and is never resent; `not_found` keeps it unknown | Provider faults are simulated; no Gmail/ATS adapter or Sent-folder search exists (JW-14); `/resume` orchestration and checkpoints (FR-RES-01/03) remain open |
| JW-13 | Implemented and verified for supported runtime paths | src/jw/suppression.py, backup.py, execution.py, actions.py, store.py (schema 12), cli.py | tests/test_jw_suppression.py (5 tests); tests/test_jw_backup.py | Opt-out, hard bounce and candidate request suppress an address everywhere, `wrong_recipient` only for that company; only SHA-256 of the normalised address is stored; rows are permanent (delete trigger aborts); approval and reservation refuse `suppressed`; a suppression journal beside the database is re-applied with the deletion journal on every restore and backup rotation, so a restored backup can neither resurrect a deleted source nor unblock an address | Reply/bounce detection that would call `suppress` automatically needs mail sync (JW-14); disclosure rules are not journaled, so restoring an older backup can still lose later disclosure decisions |
| JW-14 | Not started | src/jw/workspace.py manual attribution only | W.test_local_flow_is_draft_only_no_provider_confirmation | Manual events never provider-confirmed | Message matching and authentic receipt evidence |
| JW-15 | Not started | None | Not run | No follow-up capability | Approval, cancellation, suppression race contracts |
| JW-16 | Implemented and verified for supported runtime paths | src/jw/simulation.py, cli.py, actions.py | W.test_local_flow_is_draft_only_no_provider_confirmation; tests/test_jw_simulation.py (3 tests, 8-command effect matrix) | `--dry-run` on any command runs it on a throwaway copy and reports row deltas per table, audit events and files it would write; the live database dump is unchanged and no requested file is written; refusals still refuse; restore dry-run only validates the manifest; `Actions.simulate` reports what would be sent and every refusal without consuming the authorisation | No action adapter exists, so `external_actions` is always empty; each future adapter must add its own simulation test before activation |
| JW-17 | Not started | None; no HTTP listener | Capture command explicitly unsupported | No exposed endpoint | Protected API, Host/Origin/auth/CSRF |
| JW-18 | Implemented and verified for supported runtime paths | src/jw/untrusted.py, workspace.py, cli.py | W.test_binary_parser_is_explicitly_unsupported; test_model_output_does_not_gain_tool_authority; tests/test_jw_untrusted.py (9 tests) | PDF text is parsed by pypdf in a separate `python -I` process with an empty environment, scratch cwd, CPU/memory/file-write limits and a wall timeout; only page text is read. `archive-import` inspects ZIPs first (20 members, 5 MB, ratio 100, depth 1, traversal and encryption refused, symlinks ignored) and imports nothing unless all pass. Images refuse with `ocr_unavailable`. `check_url`/`check_redirects` block non-https, credentials, odd ports, and private, loopback, link-local, CGNAT, metadata and IPv4-mapped addresses on every hop. `html_text` escapes for HTML | No OCR engine; no fetcher uses `check_url` yet (fetching is R2); no HTML surface exists until JW-17; RLIMIT_AS is not enforced on macOS; the renderer (reportlab) runs in-process |
| JW-19 | Not started | Minimal audit and usage fields only | Metrics acceptance not run | Cost unknown, not zero | Metric dictionary, cohorts, labelled release corpus |
| JW-20 | Implemented and verified for supported runtime paths | src/jw/runs.py, execution.py, actions.py, store.py (schema 10), cli.py | W.test_process_exit_before_commit_preserves_canonical_state; test_completed_output_is_immutable_and_resume_reuses; tests/test_jw_runs.py (8 tests incl. a 9-step crash matrix) | Canonical SQLite and idempotent manual events; `pause` sets the stop flag and checkpoints; `resume` clears it, takes the lease with a new fencing token, reports version changes since the last checkpoint, expires lapsed authorisations, and stops at `reconcile_required` while any `*_unknown` exists; `progress.json` is written atomically (fsync + rename); `application-state` reduces preparation, channel and outcome separately, showing only what attempt rows prove; a kill at the write inside reserve, record, approve, revoke, delete, outcome, pin, stop or acquire leaves the database dump unchanged | `decisions.md`/`open_questions.md` are not generated; crash tests simulate a kill in-process rather than with SIGKILL |
| JW-21 | Not started | Basic immutable job snapshots only | Full discovery tests not run | No discovery adapter | SourcePost/opportunity identity, pagination, reversible merge |
| JW-22 | Implemented and verified for supported runtime paths | src/jw/csv_archive.py, history.py, store.py (schema 11), cli.py | All 9 C tests; tests/test_jw_history.py (6 tests incl. T-ONB-08) | BOM/1252, duplicate headings, multiline, exact hash, safe export; `history-import` stores original bytes, encoding (UTF-8/BOM or detected Windows-1252), headings and per-line rows; mapping names company/title/date/outcome headings and declared date formats; invalid rows reported by line while valid rows import; company+title+date duplicates reported within and across imports; identical bytes reuse the first import; outcomes are `candidate_confirmed` only when stated; `history-export` keeps original columns in order plus `jw_status`, `jw_line` | Imported rows are not yet merged into job/application records (JW-21 identity); duplicate headings collapse in `extra` (cells keep every column); YAML mapping file not read, mapping is JSON |
| JW-23 | Implemented and verified for supported runtime paths | src/jw/contracts.py, tasks.py, schedule.py, execution.py, cli.py | W.test_expiry_equality_rejects_submit; test_invalid_input_shapes_fail_closed; tests/test_jw_schedule.py (8 tests) | Aware UTC and half-open task expiry; per-channel daily caps bounded by hard caps in code (email 25, comment 15, ats 20) and allowed local hours in the candidate's IANA zone; caps count accepted, in-flight and unknown attempts per local day; `reserve` refuses with `outside_allowed_hours`/`daily_cap_reached` and the next allowed instant; DST gap starts move to the first valid minute and ambiguous ones take the first occurrence; `partial_date` keeps year/month/day precision | No background scheduler process runs queued actions at the slot (no provider exists); holidays are not modelled |
| JW-24 | Implemented and verified for supported runtime paths | src/jw/contracts.py, cli.py, traceability.py; scripts/check_traceability.py; docs/implementation/TRACEABILITY.md | W.test_invalid_input_shapes_fail_closed; release checker; tests/test_jw_traceability.py (7 tests) | Closed command contracts and stable errors; `jw schema` emits a closed JSON Schema (draft 2020-12) per command; every FR/NFR/T ID cited in `src/jw` or `tests` must exist in the PRD (`check_traceability.py` fails otherwise); TRACEABILITY.md maps all 217 PRD IDs to citing source and test files and is checked for staleness | Only 14 of 217 IDs are cited by a test today, which measures citation, not implementation; property-level types are not yet in the command schemas |
| JW-25 | Partially implemented | tests/test_jw_workspace.py; tests/test_jw_m1.py; docs/testing/TEST_STRATEGY.md | W.test_local_flow_is_draft_only_no_provider_confirmation; tests/test_jw_m1.py (7 tests: M1-01, 03/04, 05, 06, 09, 10, 12) | Synthetic end-to-end path: import, publish, rank, CV and letter drafts, mechanical gates 1-2 and format, independent review, private package, manual outcome, reducer state, zero provider rows; interrupted review resumes without losing drafts; a profile correction blocks packaging; restricted values and injected instructions stay out of review packets and the package; deletion then restore in a separate workspace purges the source; unavailable capabilities refuse | M1-02 seeded date conflict, M1-07 renderer absence, M1-08 prior application (needs JW-21 identity) and M1-11 telemetry are not exercised; visual review of page images (gate 3) is not run, so no document is ever `ready` and the six-gate claim for M1-01 is not met |

## Actual verification

2026-11-07 JW-12: 359 of 360 full-suite tests passed, including 12 new execution tests;
the one failure is the pre-existing git-checkout workspace test.
2026-11-07 JW-11: 347 of 348 full-suite tests passed, including 16 new action tests;
the one failure is the pre-existing git-checkout workspace test.

2026-11-07 JW-10: 331 of 332 full-suite tests passed, including 15 new review tests;
the one failure (test_git_checkout_cannot_hold_candidate_workspace) also fails on the prior commit.

2026-11-04 JW-09 completion: 305 full-suite tests passed, including 10 new gate
tests. A sample letter was rasterized and visually inspected.

2026-11-04 JW-08 completion: 295 full-suite tests passed, including 10 new
repair, extraction and metering tests. Model responses are synthetic.

2026-11-04 JW-07 completion: 285 full-suite tests passed, including 23 new
policy, hard-constraint, preferred-requirement, mapping-review, CLI and v4-to-v5
migration tests. Mapping verdicts in tests are synthetic; no real model was called.

2026-10-30 JW-05 completion: 262 full-suite tests passed with the pinned render
extra. guard-2 counts short added words; a host-model entailment verdict is now a
required gate; schema 4 makes schema-3 paraphrases wait for review. The 168-row
synthetic corpus (10 change categories, 12 claims) measured recall 1.0 and zero
false rejects. No real model was called: review verdicts in tests are synthetic.

2026-10-30 JW-05: 247 full-suite tests passed with the pinned render extra
installed (reportlab 4.4.9, pypdf 6.10.0). Ten new semantic tests cover the
labelled guard corpus, approval and acknowledgement rules, stale tasks after
revocation or correction, paraphrase erasure on deletion and the CLI commands.
Schema 3 is additive. JW-05 stays partial: no model-based entailment exists.

2026-10-29 JW-03: 237 full-suite tests and 76 installed-wheel workspace tests
passed. Ten new privacy/migration tests cover the owner-approved no-CV-exception
policy, scoped manual exceptions, images, stale outputs and additive schema 2.
Repository selftest, offline configuration and all 63 R1 Must mappings passed.
JW-03 is complete for supported runtime paths; source-image disclosure remains
denied. No live Gmail sending or Docker was used.

2026-10-29 integration follow-up: 227 full-suite tests pass. The pinned Distilly
writer executed successfully with synthetic input and a temporary owner root;
actual output mapping retained only supported text. Nine integration tests and
five Publora retry tests cover the qualified offline boundaries. No live sending
or draft creation occurred. See JW02_PROBE_RESULTS.md for limits; no whole ticket
is newly marked complete by these probes.

2026-10-29 fixed-renderer follow-up: 57 workspace tests passed. Synthetic CV and
letter PDFs were parsed and rasterized, then visually inspected. No Docker was
used. Renderer output is explicitly private/not-ready; no entire additional ticket
is marked complete. See FIXED_RENDERER.md in docs/architecture for limitations.
Full regression: 213 tests passed; repository selftest and release-plan checks passed.

Ranking follow-up: 205 full-suite tests passed, including 49 job-workspace tests.
The independently installed 0.1.1 wheel passed all 49 job-workspace tests.
The local flow now includes candidate-assessed ranking and a real CLI rank request.
At that checkpoint JW-07 was partial: arithmetic and a safe manual-assessment path
were implemented, but semantic mapping and full policy integration were not
(closed by the 2026-11-04 entry above). No new ticket is marked
fully complete by this checkpoint. The records below describe the previous baseline.

- 2026-10-28, Windows/Python 3.12: 34 new tests passed (25 workspace + 9 CSV).
- Full regression: 190 tests passed with src and existing validation dependencies on PYTHONPATH.
- Release checker: 63 R1 Musts mapped; consistency passed.
- Wheel built using isolated setuptools; installed into testing/jw-install.
- Installed CLI help passed. Initial no-build-isolation attempt failed because
  host setuptools was absent; declared isolated build dependencies resolved it.
- Installed-wheel suite with source PYTHONPATH removed: all 34 tests passed.
- Repository selftest: all phases clean after generated package sync. Frontmatter,
  offline configuration, actor schemas and Markdown reference checks passed.
- Initial broad Git guard rejected a home dotfiles repository. The corrected
  checkout-specific guard passes. Windows sandbox temporary cleanup required
  running the synthetic suite outside the sandbox.

No paid model evaluations, live applications or complete R1 acceptance run.
No ready PDF or real submission receipt is claimed. See
[verification strategy](../testing/TEST_STRATEGY.md) and
[integration gaps](INTEGRATION_FEASIBILITY.md).

## Resume order

Qualify rendering; implement six quality gates and bounded repairs;
complete lifecycle/backup recovery and remaining M1 scenarios. Enable provider
actions only after JW-11 through JW-16 safeguards pass.
