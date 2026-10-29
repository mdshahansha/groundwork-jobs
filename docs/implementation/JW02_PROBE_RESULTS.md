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
