# JW-02 executable integration probes

Evidence date: 2026-10-29. This checkpoint adds executable offline contracts and
private handoff packaging. It does not claim complete JW-02 acceptance or enable
provider writes. The owner explicitly chose **Skip live sending**. No message or
draft was sent or created. Connected-account identity was inspected only; account
details are not included in repository fixtures.

Validation: 227 repository tests passed; the independently installed 0.1.3 wheel
passed all 66 workspace tests with source-path imports removed. Repository
selftest, offline configuration and all 63 R1 Must dependency checks passed.
Wheel SHA-256: `537a4b3263b55af75fbc1f1cec4b587b54beb57597d79ce09fb20843ffa755b6`.

## Results and exact limits

| Boundary | Executed evidence | Limit / disposition |
|---|---|---|
| Distilly profile output | Pinned upstream owner-profile `save` command executed on synthetic Markdown; resulting file mapped to selected exact claims; invented statement stayed unassessed | Host skill discovery and model-driven profile generation were not exercised. No host linking or private source discovery. |
| Distilly absence | Existing source import, claims, published profile, CV/letter tasks and private ZIP flow pass with network and process execution forbidden | Built-in evidence selection remains usable without Distilly; no style enrichment or semantic extraction claim. |
| Gmail permissions | Separate local operation policy and provider-scope checks; send-only cannot create/send drafts or read; compose cannot bypass local draft-only policy | Offline contract only. Connected tool does not expose grant inspection. |
| Gmail uncertain send | Empty/duplicate/mismatched/incomplete candidate evidence stays `send_unknown`; no resend permitted | Even a matching synthetic record is not provider confirmation. No live lost-response recovery proof. |
| Gmail history | Bounded pagination, duplicate-event collapse, conflicting-event rejection, token-loop rejection and exceptions tested | Batch staging only. No durable cursor adapter, expired-history full rebuild, crash recovery or concurrent-arrival proof. These remain open. |
| Apify fallback | Actual wrapper tested with absent configuration and constructor failure | Unavailable requires paste; never successful empty discovery. No paid call. |
| Publora | Actual manual wrapper maps to handoff; POST transport checked for timeout, connection failure, 408/429/all 5xx and malformed success bodies | Automatic POST retry removed even with an unverified idempotency header. Ambiguous outcomes require reconciliation; live workspace writes remain disabled. |
| ATS handoff | Current CV/letter PDFs plus supported-statement answer sheet and SHA-256 manifest packaged into ZIP | Private preview only, never ready/submitted. Required portal questions remain unanswered. Final verified-attachment workflow waits for JW-09 gates. |

## Reproduction

Install `.[render-test]` and repository development requirements. Run from root:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_jw_integrations.py
python -m unittest discover -s tests -p test_publora_retry_safety.py
python tools/probe_distilly_profile.py --writer testing/distilly-probe/owner_profile.py
```

The last command requires a separately downloaded, reviewed upstream file:
[owner_profile.py at the exact pin](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/tools/owner_profile.py).
The runner checks SHA-256
`09fc5a8e3bd2ccd09d147fa2d422e853525bd30fee26b5a5da38c34ae9c12f7b`
before execution. It uses a temporary `DISTILLY_OWNER_HOME`, calls only `save`,
maps the actual file and removes temporary synthetic artifacts. It does not
download/install a host skill or call a model. Upstream code is not vendored.

## CLI contracts

`profile-map` accepts `{job_id, markdown}` and reads only currently disclosable
evidence from the published profile. It returns exact supported assertions,
unassessed-line count and `ready:false`; it does not create claims or execute
Markdown instructions. Unsupported text requires candidate correction through
the existing evidence workflow.

`handoff-preview` accepts `{cv_task_id, letter_task_id, output_path}`. Both tasks
must be completed, current and for the same job. An existing destination is never
overwritten. The ZIP contains fixed names `cv.pdf`, `letter.pdf`,
`answer-sheet.json`, and `manifest.json`. Every output remains private/not-ready;
the manifest never confirms submission. Exported copies cannot be recalled by
workspace deletion. Unsupported glyphs and overflow still block rendering.

## Remaining closure work

JW-02 remains partial: qualify the actual Distilly host inference path or approve
its explicit deferral; implement durable Gmail history/recovery adapters and
prove their failure contracts; qualify live provider behavior only when enabled
and authorized. The skipped live send is not a passing test. JW-03 has not been
advanced as a completed ticket. Full document quality gates remain JW-09 work.

## Live Gmail read-only probe (2026-11-07)

Owner-approved, read-only, through the connected Gmail account. Nothing was sent, drafted or
labelled. Raw messages and the full report stay in `testing/` (gitignored); this section holds
counts and outcomes only, no names or addresses.

| Item | Result |
| --- | --- |
| Inbox job threads read (last 60 days, query on application/interview terms) | 8 sampled of ~201 matching |
| Sent threads read | 2 |
| Messages through `MailSync.sync` in a throwaway workspace | 7 (one was the candidate's own sent mail) |
| Re-sync of the same messages | all duplicates; checkpoint unchanged (idempotent) |
| Attached to a job by company + role | 2 of 2 jobs seeded from real applications |
| Sent to review (no confident job) | 5, including a portal notice that named the company but not the role |

Classifier defects found on real mail and fixed in the same change, with regression tests in
`tests/test_jw_mail_classify.py`:

1. **Opt-out on footers.** The rule matched the bare word "unsubscribe", which appears in most
   recruiter and newsletter footers. A matched recruiter acknowledgement could have suppressed
   that recruiter. Only a person's request (remove me, unsubscribe me, do not contact, stop
   e-mailing) now counts.
2. **Newsletter as interview invite.** `\binterview\b` classified a prep-course newsletter as an
   invite. An invite now needs invitation phrasing (invite you to an interview, availability for a
   call, schedule a call, would like to interview you).
3. **Missed acknowledgements.** "Thank you for your interest ... submit your application" and
   "your application was sent to ..." were `other`; they are now acknowledgements.

Still open for JW-02: no Gmail adapter calls the Gmail API from `jw` itself (the probe used the
host's connector), so durable history-ID sync, label handling and quota behaviour are untested;
live sending stays skipped by owner decision; Distilly host inference is not run.

## Durable Gmail adapter (2026-11-07)

`src/jw/gmail.py`. Proven against `DemoGmail` (fault injection) and `ReplayGmail`:

| Contract | Result |
| --- | --- |
| First run with no cursor | Full rebuild over `messages.list`; cursor set to the mailbox `historyId` |
| Incremental | `history.list` from the cursor, paginated; re-run fetches nothing |
| Expired history (404) | Falls back to rebuild; no duplicate events |
| Crash mid-batch | Nothing partial; cursor unchanged; re-run completes |
| Provider quota (429 / rate-limit 403) | Run pauses with `retry_after`; no retry loop; next run resumes |
| Local unit budget | Stops before overspending Gmail quota units |
| Labels | Applied after commit; a label failure is counted, not rolled back |
| Scope and policy | `missing_scope` / `policy_denied` before any provider call |
| Send | Reserved first; `X-JW-Action-Id` in header and body; 4xx failed |
| Lost response | `send_unknown`, never resent, accepted only when the Sent folder holds the action ID |
| Replay of the real probe export | 7 messages synced (review queue, fresh workspace); second run fetched 0 |

## Live send qualification (2026-11-07)

Owner-approved, one message from the owner's Gmail to the same address, through the connected
Gmail tool. The attempt was reserved in a local workspace first; its action ID went in the body.

| Step | Result |
| --- | --- |
| Reserve before provider call | Attempt in flight with an action ID |
| Provider send | Gmail returned message and thread IDs |
| Lost response simulated (`record unknown`) | `send_unknown`; no resend |
| Live Sent-folder search for the action ID | 1 hit; reconcile set `sent_accepted` with the thread as evidence |
| Inbox copy synced through MailSync | Attached to the job by thread signal |

The connector cannot set custom headers, so the action ID was matched from the body; `GmailAdapter`
also sets it as `X-JW-Action-Id`.

## Distilly host inference (2026-11-07)

Upstream licence: MIT (GitHub API). Pinned SHA `0afc45c2…`; the downloaded `tools/owner_profile.py`
matches the reviewed hash `09fc5a8e…`. Claude Code acted as host and followed the pinned
`prompts/flows/owner.md` and `prompts/owner/profile_builder.md` on synthetic source material that
includes a prompt injection. The resulting profile is `tests/fixtures/distilly_host/profile.md`.

| Check | Result |
| --- | --- |
| Builder contract (`check_host_profile`) | Exact summary heading, summary ≤ 3000 chars, Sources table, no persona |
| Mapping to source claims | 3 supported lines mapped; inferred and summary prose unassessed |
| Injection ("Managed 50 people") | Not in the profile and never a claim |
| Host linking (`~/.claude/CLAUDE.md`) | Not performed |

Pinned writer save (owner-approved, 2026-11-07): `tools/qualify_distilly_host.py` verified the
writer hash, ran upstream `owner_profile.py save` under a temporary `DISTILLY_OWNER_HOME`, and
mapped the saved file: `passed: true`, 3 lines mapped, 16 unassessed, summary 336 chars, 4 inferred
lines, no forbidden text leaked, no host linking.

Not proven: `HttpGmail` against the live API (needs an OAuth token the workspace does not hold).
