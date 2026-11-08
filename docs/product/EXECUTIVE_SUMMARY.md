# Executive summary

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

This repository holds two products. **linkedin-skills** is a plugin bundle of 12 LinkedIn skills for Claude Code and Codex, with read (Apify), write (Publora) and image (Pixfaro) clients in `lib/`. **jw** is a local, evidence-first job-application workspace in `src/jw/`: a JSON command-line tool over a private SQLite workspace (schema 17), at development checkpoint, not an R1 release.

Both products draft first and act only after an explicit approval. jw drafts may state only facts the candidate supplied, and each approved e-mail is sent at most once.

At the time of writing, the validation list in `CLAUDE.md` passes and `python3 -m unittest discover -s tests` runs 562 tests green (with `requirements-dev.txt`, the `render-test` extras and `PYTHONPATH=src`).

## Benefits (parallel table)

| Benefit | How the code delivers it | Where |
| --- | --- | --- |
| No false claims in applications | Draft checker blocks figures and technologies absent from the facts file | `src/jw/lead_drafts.py` |
| Each e-mail sent at most once | Attempt reserved before the provider call; a lost response is `unknown`, never resent; `lead-reconcile` settles it from Sent | `src/jw/lead_queue.py` |
| Wrong attachment stopped | Send refused when the resume hash differs from the approved one | `src/jw/lead_queue.py` |
| Less time on dead leads | Filters with reason codes and a ranked CSV export | `src/jw/lead_filter.py` |
| No duplicate applications | Layered dedup plus applied-tracker and suppression checks | `opportunities.py`, `suppression.py` |
| Private by default | Workspace outside the repo, restricted fields kept out of CVs and model packets | `privacy.py`, `docs/architecture/DISCLOSURE_POLICY.md` |
| Drafts in your own voice | Voice rules, humanizer audit, Story Bank | `references/voice-rules.md`, `skills/linkedin-humanizer/` |
| Safe publishing | Skills show an approval card before any Publora write; manual fallback without a key | `lib/approval.py`, `lib/publora_client.py` |
| Works offline | Writing skills and local jw commands need no account | `.env.example` (all optional) |
