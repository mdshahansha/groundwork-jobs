# Lead pipeline

A daily path from job sources to reviewed applications, built on the existing workspace:
source posts and layered deduplication (JW-21), the Gmail adapter (JW-02), approved sends
(JW-04) and the audit log.

| Phase | Scope | State |
| --- | --- | --- |
| 1. Intake | `src/jw/leads.py`; `lead-import`, `lead-fetch` | Done |
| 2. Filters and fit | age ≤ 48 h, poster ≤ 4 posts a month, ≤ 4 years asked, target roles, not applied; fit score against the profile | Planned |
| 3. Drafting | per-post e-mail under the application standard; risk check | Planned |
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

LinkedIn rate limits are respected, not bypassed: a signed-in session stops at the first
unusual-traffic warning.
