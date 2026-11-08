# Feature-by-feature analysis

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

### 2.1 linkedin-skills: the 12 skills

| Skill | Purpose | Status |
| --- | --- | --- |
| [Post Writer](../../skills/linkedin-post-writer/SKILL.md) | Draft posts with the 20 hook formulas, your notes and requested Gmail context | Implemented |
| [Comment Drafter](../../skills/linkedin-comment-drafter/SKILL.md) | Comment on, or reshare, someone else's post | Implemented |
| [Reply Handler](../../skills/linkedin-reply-handler/SKILL.md) | Reply to one existing comment with the right parent target | Implemented |
| [Hook Extractor](../../skills/linkedin-hook-extractor/SKILL.md) | Identify the hook formula of an existing post and return a template | Implemented |
| [Humanizer](../../skills/linkedin-humanizer/SKILL.md) | Rewrite, audit (`--mode audit`) and profile (`--mode profile`) a draft's style | Implemented |
| [Profile Optimizer](../../skills/linkedin-profile-optimizer/SKILL.md) | Headline, About, Featured, Experience and other profile sections | Implemented |
| [Content Planner](../../skills/linkedin-content-planner/SKILL.md) | Seven-day plan with pillars, formats, hooks and engagement tasks | Implemented |
| [Repurposer](../../skills/linkedin-repurposer/SKILL.md) | Turn a blog, video, newsletter or e-mail into a native post | Implemented |
| [Employee Advocacy](../../skills/linkedin-employee-advocacy/SKILL.md) | Team publishing programme, guidelines and measurement | Implemented |
| [Thread Monitor](../../skills/linkedin-thread-monitor/SKILL.md) | Find your comments that earned author replies | Implemented |
| [Engager Analytics](../../skills/linkedin-engager-analytics/SKILL.md) | Segment the people who liked or commented on a post | Implemented |
| [Interviewer](../../skills/linkedin-interviewer/SKILL.md) | Collect experiences and figures into a Story Bank | Implemented |

"Implemented" here means the skill instructions exist and pass
`scripts/check_frontmatter.py` and the contract tests. Output quality of a skill is
graded only by `evals/run_evals.py`, which needs a model call per case: **Needs
Verification** per release.

Shared layers in `lib/`:

| Layer | Module | Calls | Without credentials |
| --- | --- | --- | --- |
| Read | `lib/apify_client.py` | `fetch_post`, `fetch_post_comments`, `fetch_user_recent_comments`, `fetch_post_engagers` (6 h LRU cache) | Paste the content |
| Write | `lib/publora_client.py` | `lib.publish(kind, ...)` for comment, reply, post, reshare; `lib.repost(...)` | Manual draft to copy |
| Image | `lib/pixfaro_client.py` | `lib.illustrate`, `lib.refine`, `lib.quote_card`, `lib.card`, `lib.brand_logo` | Image prompt only |
| Approval | `lib/approval.py` | Approval-card helpers skills call before a write (convention, not runtime enforcement) | n/a |

Apify actors called by the read client:

| Use case | Actor |
| --- | --- |
| Post body | `apimaestro/linkedin-post-detail` |
| Post comments and replies | `apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies` |
| A user's recent comments | `apimaestro/linkedin-profile-comments` |
| Post likers and commenters | `scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies` |

Provider usage may be billed; check current pricing before large fetches. For an Apify
MCP connection see [references/mcp-read-layer.md](../../references/mcp-read-layer.md).

Other parts:

- `automation/`: a Node 20 daily comment-candidate workflow. Its own header says it is
  draft-only and never publishes; publishing goes through an explicit approve queue
  (`npm run queue:build`, `queue:show`). Run from `automation/`; tests: `npm test`.
- `evals/run_evals.py`: behaviour evals against fixtures (`--list`, `--record`).
- `.claude/skills/`: relative symlinks to `skills/` so a plain clone activates the skills
  in Claude Code.

### 2.2 jw: job workspace

The CLI is `python -m jw` (installed script: `jw`). Every command takes
`--workspace <dir>` and, where needed, `--input <request.json>`, and prints one JSON object
(`{"ok": true, "result": ...}` or `{"ok": false, "error": {...}}`). `--dry-run` runs on a
throwaway copy. The workspace schema is version 17.

Tickets JW-01..25 are tracked in
[IMPLEMENTATION_STATUS.md](../../docs/implementation/IMPLEMENTATION_STATUS.md). That file
marks every ticket "Implemented and verified for supported runtime paths" (JW-01:
planning only) and also states the checkpoint is **partial, not M1 or R1 completion**.

| Area | Commands (from `COMMANDS` in `src/jw/cli.py`) | Module | Status |
| --- | --- | --- | --- |
| Workspace | `init`, `status`, `schema`, `backup`, `checkpoint`, `pause`, `resume` | `workspace.py`, `backup.py` | Implemented |
| Evidence and profile | `source-import`, `claim-add`, `claim-correct`, `profile-set`, `profile-publish`, `profile-map` | `workspace.py` | Implemented |
| Paraphrase checks (JW-05) | `paraphrase-check`, `-approve`, `-review-packet`, `-review-submit`, `-revoke` | `semantics.py` | Implemented |
| Privacy (JW-03) | `disclosure-rule`, `-grant`, `-revoke`, `-preview`, `delete-preview`, `source-delete` | `privacy.py` | Implemented |
| Jobs and ranking (JW-07) | `job-add`, `post-ingest`, `policy-set`, `policy-show`, `mapping-*`, `rank`, `rankings`, `rankings-refresh` | `policy.py`, `ranking.py`, `opportunities.py` | Implemented |
| Host-model tasks (JW-08, JW-10) | `task-create`, `task-packet`, `task-submit`, `task-failure`, `task-resume`, `extraction-*`, `usage-report`, `model-pin` | `tasks.py`, `contracts.py` | Implemented (model runs manually in the host) |
| Private drafts and PDF (JW-09) | `draft-export`, `draft-render`, `draft-verify`, `draft-readiness`, `render-font`, `handoff-preview` | `rendering.py`, `verification.py`, `visual.py` | Implemented; PDFs stay **PRIVATE DRAFT - NOT READY** |
| Mail and outcomes (JW-14, JW-15) | `mail-sync`, `mail-review`, `outcome-record`, `application-state`, `activity-record`, `activity-time` | `mailsync.py`, `followups.py` | Implemented |
| History and suppression (JW-13, JW-22) | `history-import`, `-show`, `-export`, `archive-import`, `suppress`, `merge-decide`, `merge-undo` | `history.py`, `csv_archive.py`, `suppression.py` | Implemented |
| Scheduling and metrics (JW-19, JW-23) | `schedule-set`, `schedule-next`, `metrics`, `opportunities` | `schedule.py`, `metrics.py` | Implemented |
| Local API (JW-17) | WSGI app bound to 127.0.0.1 | `api.py` | Implemented, no CLI command |
| Refused on purpose | `ready-export`, `send`, `ats-submit`, `capture`, `schedule` | `UNSUPPORTED` in `cli.py` | Unsupported: returns `unsupported_capability` |
| Restore | `restore` | `backup.py` | Listed, but `status` reports `restore: unsupported`; restore safety is unfinished |

**Lead pipeline** ([LEAD_PIPELINE.md](../../docs/implementation/LEAD_PIPELINE.md)):

| Phase | Commands | Module | Status |
| --- | --- | --- | --- |
| 1. Intake | `lead-import` (LinkedIn post export), `lead-fetch` (`naukri_mail`, `himalayas`, `remoteok`) | `leads.py` | Implemented |
| 2. Filters and fit | `lead-filter` (age, years, location, stack, role, already-applied, poster volume; 0-100 fit) | `lead_filter.py` | Implemented |
| 3. Drafting | `lead-draft-packet`, `lead-draft-submit`, `lead-drafts` | `lead_drafts.py` | Implemented |
| 4. Send queue | `lead-approve`, `lead-send`, `lead-reconcile` | `lead_queue.py`, `gmail.py` | Implemented |
| 5. Dashboard | pipeline counts, daily runs, errors | none | Planned |
| 6. Daily run | scheduled intake, filter, drafting; waits for batch approval | none | Planned |

Note: the generic `send` command is unsupported, and `status` reports
`send: unsupported`. Approved lead e-mails go only through `lead-send`, which needs a
`gmail.send` token. The CLI's `--help` text says "no external actions", which does not match `lead-send`.
