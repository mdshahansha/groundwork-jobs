# groundwork-jobs

Two tools in one repository. **linkedin-skills** is a plugin of 12 LinkedIn skills for
Claude Code and Codex that drafts posts, comments and replies and publishes only on your
approval. **jw** is a local job-application workspace that finds job posts, filters them,
checks each tailored e-mail against your own facts, and sends approved e-mails once.

Full analysis (features, architecture, market, opportunities): [docs/product/](docs/product/README.md).
Licence: [MIT](LICENSE).

## Tools

### LinkedIn skills

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

### jw lead pipeline

Run as `jw --workspace <dir> <command> --input <request.json>`. Each prints one JSON result.

| Command | What it does |
| --- | --- |
| `init`, `status` | Create a workspace; show its capabilities |
| `lead-fetch` | Pull leads from `remoteok`, `himalayas` or `naukri_mail` |
| `lead-import` | Load a LinkedIn post export (`linkedin_posts`) |
| `lead-filter` | Drop poor fits with reasons; score the rest 0-100 |
| `lead-draft-packet` | Build the brief your AI model writes the e-mail from |
| `lead-draft-submit` | Store the e-mail; block it if it claims anything not in your facts |
| `lead-drafts` | List drafts and their state |
| `lead-approve` | Approve a batch of ready drafts with your resume |
| `lead-send` | Send approved e-mails through Gmail, once each |
| `lead-reconcile` | Settle sends with an unknown result from the Sent folder |

Other jw commands (evidence, ranking, privacy, PDFs, mail sync, backups) are listed in
`COMMANDS` in `src/jw/cli.py` and in [docs/product/FEATURES.md](docs/product/FEATURES.md).

### Gmail setup tool

| Tool | What it does |
| --- | --- |
| `tools/gmail_oauth_setup.py` | One-time Google sign-in; writes the Gmail refresh token to your env file |

## Benefits

- Drafts never claim a figure or skill you did not supply.
- Each approved e-mail is sent at most once; a lost response is never resent.
- A changed resume is refused before sending.
- Old, irrelevant and already-applied leads are dropped with a reason.
- Nothing publishes or sends without your approval.
- Job data stays on your machine, outside the repository.
- Writing skills work with no account or API key.

## How to use

### LinkedIn skills

Claude Code:

```text
/plugin marketplace add mdshahansha/linkedin-skills
/plugin install linkedin-skills@linkedin-skills
```

Codex, from this checkout:

```bash
python3 scripts/sync_codex_marketplace.py
codex plugin marketplace add .
codex plugin add linkedin-skills@linkedin-skills
```

Then ask, for example: "Draft a LinkedIn post from these notes."

### jw

1. Install (Python 3.11+):

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install .
   ```

2. Create a workspace outside this repository:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main init
   ```

3. Connect Gmail once (needs a Google "Desktop app" OAuth client):

   ```bash
   python3 tools/gmail_oauth_setup.py --env /path/to/.env --client-json /path/to/client_secret.json
   ```

4. Fetch and filter leads. `fetch.json` holds `{"source": "remoteok"}`; `filter.json` can be `{}` for the default rules:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-fetch --input fetch.json
   ```

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-filter --input filter.json
   ```

5. Draft with `lead-draft-packet` and `lead-draft-submit`, approve with `lead-approve`,
   send with `lead-send`. Input fields for each command are in `src/jw/cli.py`.

### Develop

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 -m pip install -e '.[render-test]'
python3 -m unittest discover -s tests
```

Run the full validation list in [CLAUDE.md](CLAUDE.md) before pushing.
