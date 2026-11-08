# Market positioning and competitive analysis

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

### Problem

- **LinkedIn writing.** People who post and comment on LinkedIn want drafts in their own
  voice, without the phrasing that reads as machine-written, and with a safe path from
  draft to published post. The bundle drafts locally and publishes only after an explicit
  approval.
- **Job applications.** A job seeker who applies by e-mail to hiring posts repeats the
  same work every day: find fresh posts, drop the ones that do not fit, write a tailored
  e-mail that makes no false claims, send it once, and keep track. `jw` automates the
  mechanical parts and keeps the candidate in charge of every claim and every send.

### Target users

| User | Product | Need |
| --- | --- | --- |
| Founders, creators, marketers on LinkedIn | linkedin-skills | Posts, comments, replies, profile rewrite, content plans |
| Marketing or sales teams | linkedin-skills (`linkedin-employee-advocacy`) | Team posting programme and its measurement |
| Individual job seeker | jw | Lead intake, filtering, honest per-post e-mails, approved sending |
| Developers who extend agent skills | both | A tested reference for read/write/image layers and evidence gates |

### Positioning

- **Draft first, act on approval.** Nothing in either product publishes or sends without
  a concrete approval by the user. In the bundle this is a skill convention (`lib/approval.py` says it is not runtime enforcement); in jw, `lead-send` only spends authorisations created by `lead-approve`.
- **Evidence over generation.** jw drafts may only state facts the candidate supplied;
  the checker blocks unsupported figures and technologies (`src/jw/lead_drafts.py`).
- **Local and private.** jw keeps candidate data in a workspace outside the repository.
  The SQLite database is not encrypted by this application.
- **Works without accounts.** The writing skills need no API key. Integrations only add
  capabilities.

### Market

No market sizing, user counts or competitor feature claims are made here: none were
measured for this repository. **Needs Verification** before any such claim is published.


## Competitive analysis

No competitor was tested for this analysis, and the repository's conventions forbid
naming rival schedulers or image APIs in committed files. Every comparative statement
below is labelled.

| Statement | Label | Basis |
| --- | --- | --- |
| The bundle works with no API key for drafting, auditing and planning | Verified | `.env.example` marks every variable optional; `scripts/check_config.py --offline` passes with none set |
| Publishing requires an explicit approval card in every write skill | Verified (convention) | `lib/approval.py` states it is a conventions layer, not runtime enforcement |
| jw blocks unsupported figures and technologies in application e-mails | Verified | `src/jw/lead_drafts.py`, `tests/test_jw_lead_drafts.py` |
| jw never resends an e-mail whose provider response was lost | Verified | `src/jw/lead_queue.py`, `tests/test_jw_lead_queue.py` |
| Few job tools refuse to state unsupported claims | Hypothesis | Not researched; Needs Verification |
| Job seekers value one-send guarantees over volume | Hypothesis | No user research in the repo; Needs Verification |
| A combined read + write + image integration is uncommon in skill bundles | Hypothesis | Not researched; Needs Verification |
| Market size, pricing, user counts | Not stated | No data in the repo |
