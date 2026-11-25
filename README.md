# groundwork-jobs

Find fresh job posts, keep the ones that fit you, and e-mail recruiters a tailored application
with your resume. **jw** runs locally: it pulls posts from RemoteOK, Himalayas, the Naukri invites
in your Gmail and LinkedIn post exports, filters and ranks them, checks every e-mail against your
own facts, and sends only what you approve, once.

The repository also ships a [LinkedIn skills plugin](#linkedin-skills-plugin) for Claude Code and
Codex. Full analysis: [docs/product/](docs/product/README.md). Licence: [MIT](LICENSE).

## The pipeline at a glance

![Lead pipeline: seven steps, their state today, and where 2,000 posts went](docs/product/images/overview-pipeline.svg)

| Step | Today | Next | Detail |
| --- | --- | --- | --- |
| 1. Hiring signals | A post counts only if it holds an e-mail | Person-first search, signal classifier | [image](docs/product/images/step-1-hiring-signals.svg) |
| 2. The person | Author display name only | People record, author class | [image](docs/product/images/step-2-person.svg) |
| 3. Contact route | First e-mail in the text | Route hierarchy with source and confidence; never guessed | [image](docs/product/images/step-3-contact.svg) |
| 4. Opportunity | Regex fields; fit score saturates | Explicit vs assumed requirements, 10-factor score | [image](docs/product/images/step-4-opportunity.svg) |
| 5. Resume | One fixed PDF | Evidence-gated variants chosen per lead | [image](docs/product/images/step-5-resume.svg) |
| 6. E-mail | Checked against your facts | Signal-first, stricter checker | [image](docs/product/images/step-6-email.svg) |
| 7. Approve and track | Approved sends, once each | Replies, bounces and opt-outs linked and suppressed | [image](docs/product/images/step-7-approval-tracking.svg) |

Each image shows what the code does now (left) and what to build (right), with file references.
The reasoning and roadmap are in the [strategic product audit](docs/product/STRATEGY_REPORT.md).

## Quick start

1. Install (Python 3.11+) and create a workspace outside this repository:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install .
   ```

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main init
   ```

2. Connect Gmail once (needs a Google "Desktop app" OAuth client), then load the env file into
   your shell:

   ```bash
   python3 tools/gmail_oauth_setup.py --env /path/to/.env --client-json /path/to/client_secret.json
   ```

   ```bash
   set -a; . /path/to/.env; set +a
   ```

3. Fetch job posts. `fetch.json` is `{"source": "remoteok"}`, `{"source": "himalayas"}` or
   `{"source": "naukri_mail", "days": 7}`:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-fetch --input fetch.json
   ```

4. Filter them. `filter.json` can be `{}` for the default rules:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-filter --input filter.json
   ```

5. Draft, approve and send: follow [From job post to recruiter e-mail](#from-job-post-to-recruiter-e-mail).

## Job sources

| Priority | Source | Command | Needs | Recruiter e-mail |
| --- | --- | --- | --- | --- |
| 1 | RemoteOK public feed | `lead-fetch` `{"source": "remoteok"}` | Nothing | No: apply through the post link |
| 1 | Himalayas public feed | `lead-fetch` `{"source": "himalayas"}` | Nothing | No: apply through the post link |
| 1 | Naukri recruiter invites in your Gmail | `lead-fetch` `{"source": "naukri_mail", "days": 7}` | Gmail read access | No: apply on Naukri |
| 2 | LinkedIn hiring posts | `lead-import` `{"source": "linkedin_posts", "path": "..."}` | A JSON export you make elsewhere | Yes, from the post text |

Only posts that contain an e-mail address can be e-mailed. Feed and Naukri leads are still
fetched, filtered and ranked, but their drafts are blocked as `no_contact`: apply through the
link in the lead (`url`). jw never signs in to LinkedIn or scrapes it. A LinkedIn post with no
e-mail is counted as `unparsed`, never guessed. A repost (same contact e-mail, same role) is
stored once.

## jw commands

Run as `jw --workspace <dir> <command> --input <request.json>`. Each prints one JSON result.

| Command | What it does |
| --- | --- |
| `init`, `status` | Create a workspace; show its capabilities |
| `lead-fetch` | Pull job posts from `remoteok`, `himalayas` or `naukri_mail` |
| `lead-import` | Load a LinkedIn post export (`linkedin_posts`) |
| `lead-filter` | Drop poor fits with reasons; score the rest 0-100 |
| `lead-draft-packet` | Build the brief Claude writes the e-mail from |
| `lead-draft-submit` | Store the e-mail; block it if it claims anything not in your facts |
| `lead-drafts` | List drafts and their state |
| `lead-approve` | Approve a batch of ready drafts with your resume |
| `lead-send` | Send approved e-mails through Gmail, once each |
| `lead-reconcile` | Settle sends with an unknown result from the Sent folder |
| `mail-sync`, `mail-review` | Read replies and bounces; list what could not be matched |
| `tools/gmail_oauth_setup.py` | One-time Google sign-in; writes the Gmail refresh token to your env file |

Other jw commands (evidence, ranking, privacy, PDFs, backups) are listed in `COMMANDS` in
`src/jw/cli.py` and in [docs/product/FEATURES.md](docs/product/FEATURES.md).

## Benefits

- Fresh posts only: old, irrelevant and already-applied leads are dropped with a reason.
- E-mails never claim a figure or skill you did not supply.
- Nothing is sent without your approval.
- Each approved e-mail is sent at most once; a lost response is never resent.
- A changed resume is refused before sending.
- Job data stays on your machine, outside the repository.

## From job post to recruiter e-mail

This is the full path: fetch job posts, pull out the role and the recruiter's e-mail, write a
tailored e-mail that only states your own facts, and send it once with your resume after you
approve it. Steps 3 to 6 apply to leads with a recruiter e-mail; see [Job sources](#job-sources).

```mermaid
flowchart LR
    A[Job posts<br/>RemoteOK, Himalayas,<br/>Naukri mail, LinkedIn export] --> B[lead-fetch / lead-import<br/>parse role, company,<br/>contact e-mail, years]
    B --> C[lead-filter<br/>drop with reasons,<br/>fit score 0-100]
    C --> D[lead-draft-packet<br/>post + your facts<br/>+ writing standard]
    D --> E[Claude writes<br/>subject and body]
    E --> F[lead-draft-submit<br/>claim check:<br/>ready or blocked]
    F --> G[lead-approve<br/>you approve a batch<br/>with your resume]
    G --> H[lead-send<br/>Gmail, once each]
    H --> I[lead-reconcile / mail-sync<br/>Sent folder, replies, bounces]
```

Every command below is run as:

```bash
jw --workspace ~/.local/share/jw/main <command> --input <request.json>
```

Each prints one JSON object: `{"ok": true, "result": ...}` or `{"ok": false, "error": {...}}`.

### Step 0: one-time setup

1. Create the workspace (`init`) and connect Gmail with `tools/gmail_oauth_setup.py`, as in
   [Quick start](#quick-start). The tool asks for `gmail.send` and `gmail.readonly`.
2. jw reads Gmail settings from the environment, not from a file. Load the env file the setup
   tool wrote into the shell that runs jw:

   ```bash
   set -a; . /path/to/.env; set +a
   ```

   With `JW_GMAIL_CLIENT_ID`, `JW_GMAIL_CLIENT_SECRET` and `JW_GMAIL_REFRESH_TOKEN` set, jw renews
   its own 1-hour access tokens.
3. Write a **facts file** outside the repository: plain text with your name, current role,
   years of experience, skills and results you can prove. Drafts may only use what is in it.
4. Keep your **resume PDF** outside the repository. Its hash is frozen when you approve.

### Step 1: get the hiring posts

**Main sources: job feeds and Naukri mail.** `lead-fetch` reads public feeds with no account, or Naukri
recruiter invites already in your Gmail (read-only):

| `fetch.json` | Reads |
| --- | --- |
| `{"source": "remoteok"}` | RemoteOK public feed |
| `{"source": "himalayas"}` | Himalayas public feed |
| `{"source": "naukri_mail", "days": 7}` | Naukri invites in your mailbox from the last 7 days |

These leads carry the post link but no recruiter e-mail, so you apply through the link.
The same contact e-mail with the same role is treated as a repost and stored once.

**Extra source: LinkedIn posts.** jw does not sign in to LinkedIn or scrape it. Export posts elsewhere (for
example an Apify run, see `APIFY_TOKEN` under [LinkedIn skills plugin](#linkedin-skills-plugin)) into a JSON array like this:

```json
[
  {
    "text": "We are hiring a Backend Engineer (2-4 years, Python). Send your CV to jobs@example.com",
    "url": "https://www.linkedin.com/posts/example-activity-0000000000000000000",
    "author": "Example Recruiter",
    "posted_at": "2026-11-24T09:00:00Z"
  }
]
```

Only `text` is required, and it must contain the recruiter's e-mail address; a post without
one is counted as `unparsed`, never guessed. jw extracts the role, company, location,
experience range and skills from the text. Import the file with `import.json` set to
`{"source": "linkedin_posts", "path": "/path/to/posts.json"}`:

```bash
jw --workspace ~/.local/share/jw/main lead-import --input import.json
```

To read a single post by its URL, the LinkedIn skills use `lib.fetch_post(url)` through Apify;
paste that post's text into the array above to bring it into jw.

### Step 2: filter and rank

```bash
jw --workspace ~/.local/share/jw/main lead-filter --input filter.json
```

`filter.json` can be `{}`. Defaults: posted in the last 48 hours, a minimum experience of at
most 5 years, and the poster has at most 4 posts in 30 days. Roles are matched against the 50
search-term cards in `src/jw/search_terms.py`. Optional fields:

| Field | Use |
| --- | --- |
| `applied_path` | Your `job_search_tracker.csv`; contacts and company domains already applied to are dropped |
| `export_path` | Write the ranked list to a new CSV |
| `policy` | Override the filter rules |
| `limit` | How many leads to return (default 50) |

Every dropped lead has a reason code, for example too old, location, experience, excluded
stack, role or already applied. Each kept lead has a `post_id` and a fit score: 60% skill
overlap with the policy's skill list, 20% role, 20% experience, with the matched skills listed.

### Step 3: draft the e-mail with Claude

For each lead you want, build the packet:

```bash
jw --workspace ~/.local/share/jw/main lead-draft-packet --input packet.json
```

`packet.json` is `{"post_id": "<post_id>", "facts_path": "/path/to/facts.txt"}`. The packet
holds the post, the recruiter address, your facts and the writing standard: subject with
role and your name, under 180 words, resume attached, nothing invented.

Give the packet to Claude and ask for a subject and body. Then store the result with
`submit.json` set to `{"post_id": "<post_id>", "subject": "...", "body": "...",
"facts_path": "/path/to/facts.txt", "candidate": "<your name>"}`:

```bash
jw --workspace ~/.local/share/jw/main lead-draft-submit --input submit.json
```

jw checks the draft and marks it `ready` or `blocked`. It blocks:

- a number that is in neither your facts nor the post,
- a technology your facts do not list,
- salary, CTC or notice period when the post did not ask,
- stock or desperate phrasing,
- more than 180 words, or a subject over 90 characters or without your name and the role,
- a missing resume line, or a lead with no recruiter e-mail (`no_contact`).

A post that asks for date of birth, PAN or Aadhaar is flagged for you to answer personally.
Fix a blocked draft and submit again; the earlier draft is replaced. List drafts with
`lead-drafts` (`{"state": "ready"}` to filter).

### Step 4: approve a batch

```bash
jw --workspace ~/.local/share/jw/main lead-approve --input approve.json
```

`approve.json` is `{"draft_ids": ["<draft_id>", "..."], "resume_path": "/path/to/resume.pdf"}`.
Each ready draft becomes a frozen e-mail (subject, body, resume hash) with an authorisation that
lasts 24 hours (`hours` to change it). Drafts that are not ready, already approved or suppressed
are skipped with a reason.

### Step 5: send

```bash
jw --workspace ~/.local/share/jw/main lead-send --input send.json
```

`send.json` is `{"resume_path": "/path/to/resume.pdf"}` (optional `limit`, default 20). jw
sends each approved e-mail once, 4 seconds apart, with the resume attached:

- the resume must still match the approved hash, or the send is refused before Gmail is called;
- if Gmail's response is lost, the e-mail is marked `unknown` and is **never** sent again;
- `--dry-run` is refused for `lead-send`, so a test run can never send real mail.

### Step 6: confirm and follow replies

```bash
jw --workspace ~/.local/share/jw/main lead-reconcile --input reconcile.json
```

`reconcile.json` can be `{}`. It settles `unknown` sends from your Sent folder. `mail-sync`
(`{"transport": "http", "allowed": ["read"]}`) reads replies and bounces; `mail-review` lists
messages it could not match. Known gaps are tracked in
[IMPLEMENTATION_STATUS.md](docs/implementation/IMPLEMENTATION_STATUS.md), for example bounces
to `lead-send` e-mails are not yet suppressed automatically.

## LinkedIn skills plugin

A separate plugin in this repository: 12 LinkedIn skills for Claude Code and Codex that draft
posts, comments and replies and publish only on your approval. The job pipeline does not need it.

| Skill | What it does |
| --- | --- |
| [linkedin-post-writer](skills/linkedin-post-writer/SKILL.md) | Draft a new post from your notes with a proven hook |
| [linkedin-comment-drafter](skills/linkedin-comment-drafter/SKILL.md) | Comment on, or reshare, someone else's post |
| [linkedin-reply-handler](skills/linkedin-reply-handler/SKILL.md) | Reply to one existing comment |
| [linkedin-hook-extractor](skills/linkedin-hook-extractor/SKILL.md) | Find the hook formula of a post and return a template |
| [linkedin-humanizer](skills/linkedin-humanizer/SKILL.md) | Remove AI tells; audit a draft before posting |
| [linkedin-profile-optimizer](skills/linkedin-profile-optimizer/SKILL.md) | Rewrite headline, About and other profile sections |
| [linkedin-content-planner](skills/linkedin-content-planner/SKILL.md) | Seven-day content plan |
| [linkedin-repurposer](skills/linkedin-repurposer/SKILL.md) | Turn a blog, video, newsletter or e-mail into a post |
| [linkedin-employee-advocacy](skills/linkedin-employee-advocacy/SKILL.md) | Run a team posting programme |
| [linkedin-thread-monitor](skills/linkedin-thread-monitor/SKILL.md) | Find your comments that got author replies |
| [linkedin-engager-analytics](skills/linkedin-engager-analytics/SKILL.md) | Segment who liked or commented on a post |
| [linkedin-interviewer](skills/linkedin-interviewer/SKILL.md) | Collect your stories and figures into a Story Bank |

Optional connections: `APIFY_TOKEN` (read posts), `PUBLORA_API_KEY` +
`LINKEDIN_PLATFORM_ID` (publish), `PIXFARO_TOKEN` (images). Without them you paste
content in and copy drafts out. Names are in [.env.example](.env.example).

Apify actors used by the read client:

| Use case | Actor |
| --- | --- |
| Post body | `apimaestro/linkedin-post-detail` |
| Post comments and replies | `apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies` |
| A user's recent comments | `apimaestro/linkedin-profile-comments` |
| Post likers and commenters | `scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies` |

Install in Claude Code:

```text
/plugin marketplace add mdshahansha/linkedin-skills
/plugin install linkedin-skills@linkedin-skills
```

Or in Codex, from this checkout:

```bash
python3 scripts/sync_codex_marketplace.py
codex plugin marketplace add .
codex plugin add linkedin-skills@linkedin-skills
```

Then ask, for example: "Draft a LinkedIn post from these notes."

## Develop

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pip install -e '.[render-test]'
python3 -m unittest discover -s tests
```

Run the full validation list in [CLAUDE.md](CLAUDE.md) before pushing.
