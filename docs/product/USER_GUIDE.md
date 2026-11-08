# User guide (beginners)

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

### 4.1 Use the LinkedIn skills

**Claude Code:**

```text
/plugin marketplace add mdshahansha/linkedin-skills
/plugin install linkedin-skills@linkedin-skills
```

To use a local checkout, run `/plugin marketplace add .` from its root instead.

**Codex**, from this checkout:

```bash
python3 scripts/sync_codex_marketplace.py
codex plugin marketplace add .
codex plugin add linkedin-skills@linkedin-skills
```

Then ask in plain words, for example:

- "Draft a LinkedIn post from these notes. Keep the figures exactly as supplied."
- "Write three comment options for this LinkedIn post: <url>."
- "Audit this draft with the humanizer before I publish."
- "Plan seven days of content for a founder selling to engineering teams."

You always see the draft first. Publishing happens only after you approve, and only if
Publora is connected. Without it you get text to copy.

For a consistent voice, fill in [references/voice-profile.md](../../references/voice-profile.md)
and [references/story-bank.md](../../references/story-bank.md).

**Gmail as source material.** The Codex manifest declares the Gmail app in
[.app.json](../../.app.json); the host asks you to connect it. In Claude Code, connect Gmail
through the host's own connector. The bundle reads requested messages; sending,
deleting or relabelling needs explicit approval. See
[references/gmail-workflow.md](../../references/gmail-workflow.md).

### 4.2 Use jw for job applications

Keep the workspace **outside** this repository and outside synced folders.

1. Install (Python 3.11+):

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install .
   ```

2. Create a workspace and check it:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main init
   .venv/bin/jw --workspace ~/.local/share/jw/main status
   ```

3. Bring in leads. Each `--input` is a JSON file, for example `{"source": "remoteok"}`:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-fetch --input fetch.json
   ```

4. Filter, then read the reasons and the ranked list:

   ```bash
   .venv/bin/jw --workspace ~/.local/share/jw/main lead-filter --input filter.json
   ```

5. Draft each e-mail with your host model from `lead-draft-packet`, store it with
   `lead-draft-submit`, and list results with `lead-drafts`. A `blocked` draft shows why.
6. Approve the batch with `lead-approve`, then send with `lead-send`. Settle any
   `unknown` sends with `lead-reconcile`.

Sending needs Gmail access. Run this once with a Google "Desktop app" OAuth client:

```bash
python3 tools/gmail_oauth_setup.py --env /path/to/.env --client-json /path/to/client_secret.json
```

It writes `JW_GMAIL_CLIENT_ID`, `JW_GMAIL_CLIENT_SECRET` and `JW_GMAIL_REFRESH_TOKEN` to
that env file with mode 600. Publish the consent screen "In production"; in "Testing"
Google expires refresh tokens after 7 days. Input field names for every command are in
`COMMANDS` in `src/jw/cli.py` and in `docs/architecture/API_CONTRACTS.md`.

Error codes worth knowing: `unsupported_capability` means the feature is disabled, not
that it succeeded. `profile_unpublished` means correct and publish the profile first.
`stale_input` means create a new task. Do not edit the database to clear a gate.
