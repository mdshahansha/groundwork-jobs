# Lead pipeline

A daily path from job sources to reviewed applications, built on the existing workspace:
source posts and layered deduplication (JW-21), the Gmail adapter (JW-02), approved sends
(JW-04) and the audit log.

| Phase | Scope | State |
| --- | --- | --- |
| 1. Intake | `src/jw/leads.py`; `lead-import`, `lead-fetch` | Done |
| 2. Filters and fit | `src/jw/lead_filter.py`; `lead-filter` | Done |
| 3. Drafting | `src/jw/lead_drafts.py`; `lead-draft-packet`, `lead-draft-submit`, `lead-drafts` (schema 17) | Done |
| 4. Send queue | `src/jw/lead_queue.py`; `lead-approve`, `lead-send`, `lead-reconcile` | Done |
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

## Phase 4: send queue

`lead-approve` is the candidate's batch decision: each `ready` draft becomes a frozen e-mail envelope
(subject, body, resume hash) with an authorisation lasting `hours` (default 24); drafts that are not
ready, already approved or suppressed are skipped with a reason. Approving switches the e-mail channel
from `draft_only` to `approve_each_action` if needed. `lead-send` spends active authorisations once
each, paced 4 s apart: the attempt is reserved before the provider call, the resume must match the
authorised hash, the action ID rides in the `X-JW-Action-Id` header only (the adapter's
`mark_body=False`), and a lost response is `unknown` and never resent. `lead-reconcile` settles
unknowns from the Sent folder by recipient and subject, matching the header. Bounces and replies come
in through `mail-sync`. Needs a `gmail.send` token to send and `gmail.readonly` to reconcile.

Gmail auth: when `JW_GMAIL_CLIENT_ID`, `JW_GMAIL_CLIENT_SECRET` and `JW_GMAIL_REFRESH_TOKEN` are set,
the HTTP transport mints its own 1-hour access tokens and renews once on a 401, so no pasted token
is needed. `tools/gmail_oauth_setup.py --env <file>` gets the refresh token once (Desktop OAuth
client, loopback redirect, PKCE, state check) and writes it to the env file with mode 600. Publish
the consent screen "In production"; in "Testing" Google expires refresh tokens after 7 days.

Tested on the demo transport: a batch sends once and a repeat sends nothing; a lost response is
never resent and reconciles from Sent; a changed resume is refused before any provider call; a
blocked draft cannot be approved.

LinkedIn rate limits are respected, not bypassed: a signed-in session stops at the first
unusual-traffic warning.
