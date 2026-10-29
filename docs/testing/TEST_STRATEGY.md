# Test strategy and checkpoint evidence

Fixed-renderer follow-up (2026-10-29): 57 workspace tests passed. Seven new renderer
tests cover extraction, active-action absence, inert hostile markup, network/process
tripwires, overflow, glyph rejection, deterministic bytes and exclusive output.
One workspace test verifies restricted-data exclusion and revoked-source blocking.
The synthetic CV and letter were rasterized and visually inspected. Install the
`render-test` extra or updated requirements-dev.txt before running this suite.
Full repository suite: 213 tests passed; selftest reported all phases clean.
The installed 0.1.2 wheel with render-test extras passed all 57 workspace tests
without importing the source checkout.

Ranking follow-up: full suite **205 passed**, job-workspace subset **49 passed**.
The built 0.1.1 wheel was installed independently; all 49 tests passed without
source PYTHONPATH. Repository selftest, package synchronization and offline
configuration checks also passed.
Thirteen pure ranking cases cover exact score/confidence vectors, empty/unknown
components, location exclusion, salary compatibility/normalization, malformed
numbers, freshness, overlapping/partial-month experience, bounds, ambient Decimal
context and deterministic tie order. Two workspace cases verify current claims,
transferable evidence and CLI dispatch; the core synthetic flow now ranks before
drafting. Earlier baseline counts below remain historical evidence.

Synthetic fixtures only. No API keys, live applicant messages or paid calls.
The new suite tests the local checkpoint, not full M1/R1 acceptance.

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p 'test_jw_*.py'
```

Observed on 2026-10-28, Windows/Python 3.12: **34 tests passed**. This consists of
25 workspace tests and 9 CSV utility tests. Initial failures exposed an overly
broad Git-directory guard; the corrected guard protects this project checkout.
Windows sandbox temporary-directory cleanup also required execution outside
the sandbox. The final successful run did not skip any workspace test.

Workspace coverage: import identity, classification, immutable corrections,
conflict publication, restricted-data exclusion across packets/reviews/exports,
invented compound assertions, unknown evidence, retry budget, tool injection,
contact/version/date invalidation, unchanged private evidence reuse, eight
concurrent task creations, immutable completed output, quota resume, isolated
review, deletion descendants, transactional rollback, process exit before commit,
expiry equality, malformed schemas, unsupported binaries, newer schemas, consent
and explicit unsupported capabilities. The synthetic flow prepares CV and letter
text drafts and records a manual outcome; it does not pass document quality gates.

CSV coverage: exact original-byte hashing, UTF-8 BOM, explicit Windows-1252,
duplicate/unknown headings, embedded newlines/quotes, invalid widths/quotes,
5 MiB boundary, formula-safe headings/cells, deterministic exports and no global
CSV-parser configuration mutation. Historical persistence/mapping remains absent.

Clean wheel installation and the installed-wheel suite also passed (34 tests).
The full legacy plus runtime suite passed all 190 tests. Repository selftest,
frontmatter, actor schemas, offline configuration and Markdown references passed.
The generated plugin package was synchronized and its selftest check passed.

Remaining required tests include render/visual/format fixtures, actual model evaluations, semantic paraphrases,
mapping/ranking, source parser sandbox escapes, old-backup erasure/replay,
provider fault injection, approval races, local API security and mature-cohort
metrics. Status and final validation results belong in IMPLEMENTATION_STATUS.md.
No aggregate passing unit count substitutes for an unimplemented release gate.
