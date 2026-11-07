# Lead pipeline

A daily path from job sources to reviewed applications, built on the existing workspace:
source posts and layered deduplication (JW-21), the Gmail adapter (JW-02), approved sends
(JW-04) and the audit log.

| Phase | Scope | State |
| --- | --- | --- |
| 1. Intake | `src/jw/leads.py`; `lead-import`, `lead-fetch` | Done |
| 2. Filters and fit | `src/jw/lead_filter.py`; `lead-filter` | Done |
| 3. Drafting | `src/jw/lead_drafts.py`; `lead-draft-packet`, `lead-draft-submit`, `lead-drafts` (schema 17) | Done |
| 4. Send queue | batch approval, `jw` send with action IDs, bounce and reply handling through `mail-sync` | Planned |
| 5. Dashboard | pipeline counts, daily runs, errors | Planned |
| 6. Daily run | scheduled intake, filter and drafting; waits for batch approval | Planned |

## Phase 1: intake

Sources are read-only and legitimate. Nothing in intake signs in, scrapes a page or applies.

| Source | How it arrives | Parser |
| --- | --- | --- |
| `naukri_mail` | Naukri recruiter invites already in the mailbox, read through a `gmail.readonly` token (`lead-fetch`) | `parse_naukri_invite` |
| `linkedin_posts` | Hiring posts exported elsewhere (Apify run, or a paced signed-in browser session) as `{text, url, author, posted_at}` (`lead-import`) | `parse_linkedin_post` |
| `himalayas`, `remoteok` | Public feeds, no account or key (`lead-fetch`) | `parse_himalayas`, `parse_remoteok` |

Each parser is pure and returns a post or `None`; a format change shows as `unparsed`, never as a
wrong job. Posts keep `posted_at`, `min_years`, `max_years`, `contact_email` and `skills` for the
phase-2 filters. Deduplication is `Opportunities.ingest`, plus one lead rule: the same contact
e-mail with the same role is a repost and reuses the existing post.

```text
jw --workspace <ws> lead-fetch  --input '{"source": "remoteok"}'
jw --workspace <ws> lead-fetch  --input '{"source": "naukri_mail", "token_env": "JW_GMAIL_TOKEN", "days": 7}'
jw --workspace <ws> lead-import --input '{"source": "linkedin_posts", "path": "posts.json"}'
```

Live run, 2026-11-07, throwaway workspace:

| Source | Seen | New | Reposts folded | Unparsed | Re-run new |
| --- | --- | --- | --- | --- | --- |
| LinkedIn posts (Apify export) | 2000 | 785 | 439 | 776 (no contact e-mail) | 0 |
| RemoteOK | 100 | 99 | 0 | 1 (legal notice) | 0 |
| Himalayas | 20 | 20 | 0 | 0 | 0 |

Not yet run live: `naukri_mail` (needs a current `gmail.readonly` token); parser tested on a
synthetic invite with the real template's structure (`tests/fixtures/leads/naukri_invite.html`).

## Phase 2: filters and fit

`lead-filter` checks one post per opportunity against the candidate's rules; every failure is a
reason code. Policy defaults: posted ≤ 48 h ago, minimum years asked ≤ 4, poster ≤ 4 posts in 30
days. Target roles are judged on the post text (LinkedIn, whose title is a guess) or the title
(feeds). A remote feed role must be open to India, worldwide or Asia. `applied_path` reads
`job_search_tracker.csv`: a contact e-mail, or a company domain for non-free mail, already applied
to drops the lead. Poster volume counts only posts this workspace has seen, so LinkedIn leads keep
`checks_pending: poster_unverified` until a profile check. Survivors get a 0-100 fit (60 % skill
overlap with the profile stack, 20 % role, 20 % experience) with the matched skills listed.
`export_path` writes the ranked list as CSV (exclusive create).

Live run over the phase-1 workspace, 2026-11-07: 904 opportunities, 8 kept. Dropped: location 592,
experience 428, excluded stack 368, too old 270, role 98, applied 82, poster volume 16 (a lead can
fail several rules).

## Phase 3: drafting

The host model writes each e-mail from `lead-draft-packet` (post, candidate facts file, writing
standard). `lead-draft-submit` stores it in `lead_drafts` with a risk report and state `ready` or
`blocked`. Blocking checks: a figure in neither facts nor post, a technology the facts lack, stock or
desperate wording, CTC/salary/notice when the post did not ask, over 180 words or a 90-character
subject, a subject without the candidate's name and role, no attached-resume line, no contact
address. A post asking for date of birth, PAN or Aadhaar is flagged for the candidate, not blocked.
Resubmitting a lead discards its earlier draft. The facts file stays outside the repository.

Live review, 2026-11-07, caught six filter defects in phase 2 before any draft (women-only drive,
"5.1-11 years" read as 1, Texas/OPT, a ₹6,000/month project-manager gig, security engineer,
unrelated stacks); all fixed with regression tests. Of the 4 leads left, 2 drafts are ready
(Aquainsys, Infosys with a date-of-birth flag). The checker blocked "Django" in two drafts because
the candidate profile does not support it; one draft was reworded, the Django-first lead dropped,
and an ML/sensor-data lead was skipped as unsupported.

LinkedIn rate limits are respected, not bypassed: a signed-in session stops at the first
unusual-traffic warning.
