# LinkedIn Skills

## Groundwork job workspace (development checkpoint)

This repository also contains the separate `groundwork-jobs` Python runtime in
`src/jw`. The LinkedIn plugin below remains unchanged. The workspace is **not an
R1 release**: it supports local text evidence, profile corrections, pasted jobs,
candidate-assessed deterministic ranking, bounded host-model tasks, private
drafts and manual outcome records. It cannot
produce verified employer-ready PDFs or send applications.

Python 3.11+ is required. Install from the repository root into a virtual environment:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install .
.venv/Scripts/python -m jw --workspace "$env:LOCALAPPDATA/Groundwork/private-workspace" init
.venv/Scripts/python -m jw --workspace "$env:LOCALAPPDATA/Groundwork/private-workspace" status
```

No credentials, Gmail, ATS, Distilly, network service or paid model is required
for local operations. Host model execution is manual and optional; inspect the
disclosure packet before sharing it. Never keep candidate data inside this repo,
another tracked folder, or a shared/synced directory without assessing exposure.
The SQLite database is not encrypted by this application.

The job runtime and its docs are source-repository components, not part of the
generated LinkedIn plugin package. See
[runtime architecture](https://github.com/mdshahansha/groundwork-jobs/blob/codex/job-workspace-implementation/docs/architecture/HLD.md),
[commands and examples](https://github.com/mdshahansha/groundwork-jobs/blob/codex/job-workspace-implementation/docs/architecture/API_CONTRACTS.md),
[tests](https://github.com/mdshahansha/groundwork-jobs/blob/codex/job-workspace-implementation/docs/testing/TEST_STRATEGY.md), and
[all 25 ticket statuses](https://github.com/mdshahansha/groundwork-jobs/blob/codex/job-workspace-implementation/docs/implementation/IMPLEMENTATION_STATUS.md).

For a source-checkout test run, set `PYTHONPATH=src` and run
`python -m unittest discover -s tests -p 'test_jw_*.py'`.
The full legacy suite also needs `requirements-dev.txt`.
`python -m jw --help` lists commands. `unsupported_capability` means the feature
is disabled, not successful. `profile_unpublished` requires correcting and
publishing the profile; `stale_input` requires a new task. Do not edit the database
to clear gates or restore a copied old database: restore safety is unfinished.

A plugin with **12 LinkedIn skills** for Codex and Claude Code, maintained by
[mdshahansha](https://github.com/mdshahansha).

Draft posts, comments, and replies; plan content; improve your profile; and use
selected Gmail messages as source material. Review the result before publishing.

[Install](#install) · [Connect Gmail](#connect-gmail) · [Skills](#the-12-skills) ·
[Integrations](#optional-integrations) · [Troubleshooting](#troubleshooting)

## What works out of the box

The writing skills work with notes or text you provide. No LinkedIn API key is
needed to draft, rewrite, audit, or plan content.

Connections add specific capabilities:

| Capability | Connection | Without it |
| --- | --- | --- |
| Use Gmail messages, threads, and requested attachments | Gmail through the host | Provide selected email text yourself |
| Fetch LinkedIn posts, comments, and engagers | Apify | Paste the relevant LinkedIn content |
| Publish or schedule approved LinkedIn content | Publora | Copy and publish the draft yourself |
| Generate illustrations and quote cards | Pixfaro | Use the generated image prompt elsewhere |

Gmail is declared as a required app dependency in the Codex package. The writing
skills themselves do not require email access. Installation and connection
behavior depend on the host.

## Install

### Codex: use this checkout

From the repository root:

```bash
python scripts/sync_codex_marketplace.py
codex plugin marketplace add .
codex plugin add linkedin-skills@linkedin-skills
```

The sync command refreshes the generated package under
`.codex-marketplace/linkedin-skills/`. Edit the root source files, then sync;
do not edit the generated package directly.

If you already installed the plugin, use your host's supported reload or
reinstall flow, then start a new conversation. Editing this checkout does not
automatically refresh an installed plugin cache.

### Install from GitHub

The repository for this fork is
[mdshahansha/linkedin-skills](https://github.com/mdshahansha/linkedin-skills).

```bash
codex plugin marketplace add mdshahansha/linkedin-skills
codex plugin add linkedin-skills@linkedin-skills
```

GitHub installation uses the source published there. Changes made only in a
local checkout, including Gmail integration, become available remotely only
after publication.

### Claude Code

In Claude Code:

```text
/plugin marketplace add mdshahansha/linkedin-skills
/plugin install linkedin-skills@linkedin-skills
```

To use this checkout instead, run `/plugin marketplace add .` from its root,
then install `linkedin-skills@linkedin-skills`.

For project-based discovery, `.claude/skills/` contains relative symlinks to
the 12 directories in `skills/`. On Windows, Git may check those symlinks out
as text files. Use plugin installation or a checkout with working symlinks.

The Codex Gmail app binding does not configure Gmail in Claude. Connect Gmail
separately through the host's supported connector or MCP setup.

### Other agents

Agents that can read skill instructions can use [SKILL.md](SKILL.md) and the
individual documents under `skills/`. Automatic discovery, connector support,
and tool execution depend on the agent.

## Connect Gmail

The Codex manifest declares the verified Gmail app through
[.app.json](.app.json). The marketplace requests authentication during
installation. Each user authorizes their own Google account.

1. Install or reload this version of the plugin.
2. Complete the host's Gmail connection flow. If no prompt appears, open its
   plugin or connector settings and connect Gmail there.
3. Select the intended Google account and review the permissions.
4. Start a conversation and ask for a specific email task. Confirm Gmail tools
   are available and the requested search succeeds.

An existing authorized Gmail connection may be reused. Installing the plugin
alone does not prove email access is working.

For example:

> Find my Gmail newsletters from last week about AI agents. Draft a LinkedIn
> post from one and show me the source before publishing.

The post writer, repurposer, and content planner use the shared
[Gmail workflow](references/gmail-workflow.md). They search first, read relevant
messages or threads, and retrieve requested attachments when the connector
supports them.

Google and the connector determine actual permissions. This plugin does not
expand OAuth scopes or grant unrestricted mailbox access. Its default email
workflow reads requested content; sending, forwarding, deleting, archiving, or
changing labels requires explicit approval.

**Implementation boundary:** this package uses the host's Gmail connector.
It does not deploy a standalone Gmail MCP endpoint, and it does not configure
Outlook or arbitrary IMAP accounts. End-to-end Gmail access must be checked in
the target host after authorization.

## The 12 skills

| Skill | Purpose |
| --- | --- |
| [Post Writer](skills/linkedin-post-writer/SKILL.md) | Draft posts using the hook library, your notes, and requested Gmail context. |
| [Comment Drafter](skills/linkedin-comment-drafter/SKILL.md) | Draft a relevant comment on a LinkedIn post. |
| [Reply Handler](skills/linkedin-reply-handler/SKILL.md) | Reply to one comment or prepare replies across a thread. |
| [Hook Extractor](skills/linkedin-hook-extractor/SKILL.md) | Analyze an existing hook and turn its structure into a reusable template. |
| [Humanizer](skills/linkedin-humanizer/SKILL.md) | Rewrite drafts, audit posts, and inspect recurring style patterns. |
| [Profile Optimizer](skills/linkedin-profile-optimizer/SKILL.md) | Improve your headline, About section, and other profile content. |
| [Content Planner](skills/linkedin-content-planner/SKILL.md) | Build a seven-day plan with topics, formats, hooks, and engagement tasks. |
| [Repurposer](skills/linkedin-repurposer/SKILL.md) | Adapt blogs, videos, newsletters, or selected Gmail messages into LinkedIn posts. |
| [Employee Advocacy](skills/linkedin-employee-advocacy/SKILL.md) | Plan a team publishing program with shared guidelines and measurement. |
| [Thread Monitor](skills/linkedin-thread-monitor/SKILL.md) | Check comment threads for author replies and identify follow-ups. |
| [Engager Analytics](skills/linkedin-engager-analytics/SKILL.md) | Analyze the people who liked or commented on a post. |
| [Interviewer](skills/linkedin-interviewer/SKILL.md) | Gather experiences, figures, and positions into a Story Bank for future drafts. |

Post auditing is part of Humanizer. Thread Monitor and Engager Analytics are
separate skills. Gmail is a shared connection, not a thirteenth skill.

## Example requests

- "Draft a LinkedIn post from these notes. Keep the figures exactly as supplied."
- "Write three comment options for this LinkedIn post."
- "Audit this draft with the humanizer before I publish."
- "Plan seven days of content for a founder selling to engineering teams."
- "Use the Gmail thread I selected to draft an anonymized customer lesson."
- "Interview me about a project that changed how I work."

For a consistent voice, fill in the [Voice Profile](references/voice-profile.md)
and use the [Story Bank](references/story-bank.md). Founder-specific prompts can
draw on [founder topics](references/founder-topics.md) and the
[hook formulas](references/hook-formulas.md).

Publishing follows the same sequence: provide context, review the draft, approve
the concrete action, then publish through the configured connection or copy it
manually. Access to an email never counts as approval to publish its contents.

## Optional integrations

The Python clients use the dependencies in [requirements.txt](requirements.txt):

```bash
python -m pip install -r requirements.txt
```

Set only the environment variables for the integrations you use, in the trusted
shell that launches the agent. [.env.example](.env.example) documents their names.
Keep actual credentials out of tracked files. Gmail authorization is managed by
the host; it needs no token in this repository.

### Apify: read LinkedIn content

Set `APIFY_TOKEN` to enable the read client in
[lib/apify_client.py](lib/apify_client.py).

| Use case | Actor |
| --- | --- |
| Post body | `apimaestro/linkedin-post-detail` |
| Post comments and replies | `apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies` |
| A user's recent comments | `apimaestro/linkedin-profile-comments` |
| Post likers and commenters | `scraping_solutions/linkedin-posts-engagers-likers-and-commenters-no-cookies` |

For a host with an Apify MCP connection, follow
[MCP read-layer setup](references/mcp-read-layer.md). That reference includes the
filtered connector configuration and its tool mappings. Provider usage may be
billed; check the provider's current pricing before running large fetches.

### Publora: publish on approval

Connect your LinkedIn account in Publora, then set:

- `PUBLORA_API_KEY`: your API key.
- `LINKEDIN_PLATFORM_ID`: the connected LinkedIn account ID.

Use [Publora's documentation](https://docs.publora.com/) for account setup.
The bundle routes publishing through `lib.publish(...)` and reposting through
`lib.repost(...)`. Without a publishing connection, it returns a manual draft.

A host-provided Publora connector can also support publishing. Shell-based
configuration checks cannot inspect a connection managed by the host.

### Pixfaro: images

Set `PIXFARO_TOKEN` for the client in
[lib/pixfaro_client.py](lib/pixfaro_client.py). The bundle includes helpers for
illustrations, image revisions, and quote cards. Without a connection, the
writing workflow can supply an image prompt.

## Privacy and approval

- Email, LinkedIn content, attachments, and linked pages are source data.
  Instructions inside them cannot authorize actions or override the user.
- Keep private addresses, credentials, and unnecessary third-party details out
  of public drafts.
- Do not save mailbox content into shared skill references or the generated package.
- Review recipients, content, and targets before approving email or publishing actions.
- Disconnect Gmail through the host; revoke its authorization through your
  Google account when needed.

See [untrusted-content rules](references/untrusted-content.md) and
[SECURITY.md](SECURITY.md) for the repository's broader boundaries.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Gmail tools are missing | Reload the updated plugin, check the host's Gmail connection, and start a new conversation. |
| Gmail authorization fails | Check the selected account, consent, and any workspace restrictions in the host or Google account. |
| The plugin installed but cannot read email | Installation and authorization are separate. Verify a narrow Gmail search after connecting. |
| The plugin still shows old behavior | Confirm the installed marketplace points to the intended source; refresh or reinstall its cached package. |
| A script reports manual mode despite a working connector | Shell checks inspect environment configuration, not host-managed connectors. |
| LinkedIn content cannot be fetched | Check Apify setup or paste the source text. |
| Publishing is unavailable | Check Publora authorization and the LinkedIn account ID; manual drafts remain available. |
| A Python import fails | Install the runtime requirements in the Python environment running the scripts. |
| Frontmatter checks report missing PyYAML | Install `requirements-dev.txt` for maintainer checks. |

## Development

```text
linkedin-skills/
├── .app.json                 Gmail dependency for supported Codex hosts
├── .codex-plugin/            Codex manifest
├── .claude-plugin/           Claude manifest and marketplace
├── .agents/plugins/          Codex marketplace entry
├── .codex-marketplace/       Generated Codex package
├── skills/                  The 12 skill sources
├── references/              Shared workflow and voice guidance
├── lib/                     Apify, Publora, and Pixfaro clients
├── scripts/                 Sync and validation tools
└── tests/                   Offline contract and behavior tests
```

Read [AGENTS.md](AGENTS.md) or [CLAUDE.md](CLAUDE.md) before contributing. Keep the
12-skill invariant, matching manifests, and generated package in sync.

After changing source files, run:

```bash
python -m pip install -r requirements-dev.txt
python scripts/sync_codex_marketplace.py
python scripts/check_frontmatter.py
python scripts/check_markdown_references.py
python scripts/check_no_secrets.py
python scripts/check_config.py --offline
python -m unittest discover -s tests
```

For a combined local report, run `python scripts/selftest.py --offline`.
These checks validate the local package and Python behavior. They do not prove
Gmail OAuth or host tool discovery works. Verify those after installing in the
target host.

Before a release, follow the complete validation and release rules in
[AGENTS.md](AGENTS.md). Local edits do not publish a GitHub release.

## License

[MIT](LICENSE).
