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
| JW-04 | Partially implemented | src/jw/workspace.py, store.py | W.test_deletion_erases_all_dependent_packet_text; test_delete_follows_correction_lineage; test_failed_delete_rolls_back_whole_transaction | Atomic logical erasure includes descendants | Independent deletion journal, backups, restore purge |
| JW-05 | Partially implemented | src/jw/tasks.py, workspace.py | W.test_factual_invention_unknown_reference_and_retry_cap; test_metric_rounding_and_unsupported_study_block | Exact assertions required; invented clauses rejected | Semantic entailment, approved paraphrases, labelled corpus |
| JW-06 | Partially implemented | src/jw/tasks.py, workspace.py | W.test_contact_edit_invalidates_pending_and_completed_outputs; test_version_and_calculation_date_invalidate; test_concurrent_identical_requests_have_one_logical_task | Immutable fingerprints; eight concurrent requests converge | Real templates/research/model pins, ranking refresh |
| JW-07 | Partially implemented | src/jw/ranking.py, workspace.py, cli.py; docs/architecture/SCORING.md | tests/test_jw_ranking.py; W.test_rank_checks_current_claims_and_hard_location; test_transferable_mapping_cannot_claim_direct_support | Exact weighted vectors, unknowns, CTC/base and hourly handling, overlap union, conservative months, CLI mapping and stable ties pass | Product approval of provisional formulas, semantic mapping, full hard-policy integration and preferred-requirement storage |
| JW-08 | Partially implemented | src/jw/contracts.py, tasks.py | W.test_model_output_does_not_gain_tool_authority; test_quota_resume_keeps_prior_draft_and_budget | Closed draft/review schemas, bounded bytes/attempts, unknown cost | Extraction/mapping/repair schemas, actual runner metering |
| JW-09 | Partially implemented | src/jw/rendering.py, tasks.py, cli.py; docs/architecture/FIXED_RENDERER.md | Renderer overflow/glyph/injection/format probes; workspace privacy and staleness | Fixed-template private PDF path works without Docker or LaTeX execution | Full layout/visual/reviewer gates, required-format workflow, multilingual support |
| JW-10 | Partially implemented | src/jw/tasks.py | W.test_isolated_review_cannot_assert_readiness | Fresh packet excludes rationale/history | Visual checks, repairs, held-out corpus and recall |
| JW-11 | Not started | None; external commands disabled | Unsupported-command test is boundary proof only | No action provider exists | Immutable action envelopes and approvals |
| JW-12 | Not started | None | Provider faults not tested | No action provider exists | Reservations, fencing, uncertain-outcome recovery |
| JW-13 | Not started | src/jw/cli.py blocks restore | W unsupported-command test | Restore disabled, not implemented | Durable recovery boundary, suppression/deletion reconciliation |
| JW-14 | Not started | src/jw/workspace.py manual attribution only | W.test_local_flow_is_draft_only_no_provider_confirmation | Manual events never provider-confirmed | Message matching and authentic receipt evidence |
| JW-15 | Not started | None | Not run | No follow-up capability | Approval, cancellation, suppression race contracts |
| JW-16 | Partially implemented | src/jw/tasks.py, cli.py | W.test_local_flow_is_draft_only_no_provider_confirmation | Private export is not ready or sent | Full dry-run/simulation/preview effect matrix |
| JW-17 | Not started | None; no HTTP listener | Capture command explicitly unsupported | No exposed endpoint | Protected API, Host/Origin/auth/CSRF |
| JW-18 | Partially implemented | src/jw/contracts.py, workspace.py, cli.py | W.test_binary_parser_is_explicitly_unsupported; test_model_output_does_not_gain_tool_authority | Bounded text only; no fetch/shell/rendered HTML | PDF/OCR/archive sandbox, SSRF and XSS fixtures |
| JW-19 | Not started | Minimal audit and usage fields only | Metrics acceptance not run | Cost unknown, not zero | Metric dictionary, cohorts, labelled release corpus |
| JW-20 | Partially implemented | src/jw/store.py, workspace.py, tasks.py | W.test_process_exit_before_commit_preserves_canonical_state; test_completed_output_is_immutable_and_resume_reuses | Canonical SQLite and idempotent manual events | Reducer, pause/lease ownership, complete crash matrix |
| JW-21 | Not started | Basic immutable job snapshots only | Full discovery tests not run | No discovery adapter | SourcePost/opportunity identity, pagination, reversible merge |
| JW-22 | Partially implemented | src/jw/csv_archive.py, tests/test_jw_csv_archive.py | All 9 C tests | BOM/1252, duplicate headings, multiline, exact hash, safe export | Historical persistence, mapping, repeat-import identity |
| JW-23 | Partially implemented | src/jw/contracts.py, tasks.py | W.test_expiry_equality_rejects_submit; test_invalid_input_shapes_fail_closed | Aware UTC and half-open task expiry | Scheduler, DST, cap zones, partial-date experience |
| JW-24 | Partially implemented | src/jw/contracts.py, cli.py; docs/architecture | W.test_invalid_input_shapes_fail_closed; release checker | Closed command contracts and stable errors | Full PRD schemas and traceability |
| JW-25 | Partially implemented | tests/test_jw_workspace.py; docs/testing/TEST_STRATEGY.md | W.test_local_flow_is_draft_only_no_provider_confirmation | Synthetic import/correct/draft/private-export/manual-record flow | Ranking, renderer, all quality gates, complete M1 |

## Actual verification

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
JW-07 remains partial: arithmetic and a safe manual-assessment path are implemented,
but semantic mapping and full policy integration are not. No new ticket is marked
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

Complete purpose/channel disclosure and semantic assertions; finish semantic
mapping and ranking policy integration; qualify rendering; implement six quality gates and bounded repairs;
complete lifecycle/backup recovery and remaining M1 scenarios. Enable provider
actions only after JW-11 through JW-16 safeguards pass.
