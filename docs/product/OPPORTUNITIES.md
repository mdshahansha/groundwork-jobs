# Prioritised opportunities

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

Ordered by value to the current user and by how much code already exists.

| # | Opportunity | Why | Effort |
| --- | --- | --- | --- |
| 1 | Lead pipeline phase 6: daily run | Intake, filter and drafting already exist as commands; a scheduled run that stops at batch approval removes the daily manual chain | Medium |
| 2 | Lead pipeline phase 5: dashboard | Counts per stage, sends, unknowns and errors; data is already in the workspace | Medium |
| 3 | Poster-volume check for LinkedIn leads | Leads keep `checks_pending: poster_unverified` until a profile check | Small |
| 4 | Live `naukri_mail` run | Parser is tested only on a synthetic invite (per LEAD_PIPELINE.md) | Small |
| 5 | Fix CLI help text | `--help` says "no external actions" while `lead-send` sends | Trivial |
| 6 | Safe restore | `restore` is listed but reported unsupported | Medium |
| 7 | Workspace encryption | SQLite holds personal data unencrypted | Medium |
| 8 | Recorded eval runs per release | Skill quality is only graded by `evals/run_evals.py` on demand | Small |
