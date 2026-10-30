# CLI contracts, storage schema version 3

JW-05 adds `paraphrase-check` (`claim_id`, `text`), `paraphrase-approve`
(`claim_id`, `text`, `confirm`, optional `acknowledge: ["new_content"]`) and
`paraphrase-revoke` (`paraphrase_id`). Draft assertions may equal claim text or an
approved paraphrase listed in the packet as `approved_paraphrases`. Rejections
return reason codes only. See [semantic checks](SEMANTIC_CHECKS.md).

JW-03 adds `disclosure-rule`, `disclosure-grant`, `disclosure-revoke` and
`disclosure-preview`. See [payloads and policy](DISCLOSURE_POLICY.md). Existing
payloads remain compatible; stored policy-1 tasks require regeneration.

No HTTP endpoints exist. Local process access relies on OS account/file access,
not an application authentication token. The proposed protected API remains
unimplemented. Never expose this CLI through an unauthenticated web wrapper.

Invocation: `jw --workspace PRIVATE_DIRECTORY COMMAND --input REQUEST.json`.
`python -m jw` is equivalent. `init`, `status` and `profile-publish` take no input.
`source-import` takes raw UTF-8 text instead of JSON and optional
`--provenance document|candidate_confirmation` and
`--sensitivity public|private|restricted` (default private).

| Command | Required JSON fields | Optional fields |
|---|---|---|
| profile-set | name, email | None |
| claim-add | source_id, start, end | sensitivity, state (`active` or `conflict`) |
| claim-correct | claim_id, text | None |
| job-add | company, title, description, requirements (string list) | requisition |
| rank | job_id, mapping, assessment | None |
| task-create | job_id, kind (`draft_cv`, `draft_letter`, `review`), consent=true | draft_id (required only for review) |
| task-packet, task-resume, draft-export | task_id | None |
| draft-render | task_id, output_path (new .pdf file) | None |
| profile-map | job_id, markdown | None |
| handoff-preview | cv_task_id, letter_task_id, output_path (new .zip file) | None |
| task-submit | task_id, response | None |
| task-failure | task_id, reason (`quota`, `rate_limit`, `timeout`, `refusal`) | None |
| delete-preview | source_id | None |
| source-delete | source_id, confirm=true | None |
| outcome-record | job_id, kind, effective_at | None |

Unknown/missing keys fail. IDs come from command responses, never invented IDs.
General input is capped at 1,000,000 bytes; model packets/results at 64,000 bytes.
Duplicate JSON keys, nonfinite numbers and invalid UTF-8 fail. Error output never
echoes source text. Argparse syntax errors use stderr and exit 2.

Success: `{"ok":true,"result":{...}}`, exit 0. Domain/input failure:
`{"ok":false,"error":{"code":"stale_input","message":"..."}}`, exit 2.
Storage/OS errors use `storage_error`, exit 3. Disabled `send`, `ats-submit`,
`ready-export`, `capture`, `restore` and `schedule` return `unsupported_capability`.
No external effect occurs.

`draft-render` is a local filesystem export, not a ready export or a submission.
Install `.[render]`; supply an existing private destination directory. It rejects
existing files, unsupported glyphs and overfull pages. See [renderer limits](FIXED_RENDERER.md).

`profile-map` maps manually supplied owner-profile Markdown to exact current
public evidence; unsupported lines remain unassessed, never new claims.
`handoff-preview` packages current same-job CV/letter private PDFs, a supported
statement sheet and hash manifest. It remains not-ready and performs no
submission. See [integration probe contracts](../implementation/JW02_PROBE_RESULTS.md).

Example draft response body, using a real returned claim ID and its exact text:

```json
{
  "output": {"assertions": [{"text": "Built Python services.", "claim_id": "RETURNED_CLAIM_ID"}]},
  "usage": {"model": "host-model-version", "input_tokens": null, "output_tokens": null}
}
```

Wrap that body as `{"task_id":"RETURNED_TASK_ID","response":BODY}` for
`task-submit`. Null usage means unknown, not zero. Review output instead contains
`findings`, a list of objects with `severity`, `code`, and `assertion_index`.
Allowed severities: critical/major/minor. Codes: unsupported_assertion,
wrong_contact, style. Index is a valid zero-based draft assertion index or null.
An empty review does not pass rendering/visual/format gates.

Manual outcomes: prepared, manual_applied, interview, offer, rejected, withdrawn.
`effective_at` requires an ISO-8601 UTC offset and cannot be future-dated. Equal
job/kind/normalized timestamp is idempotent. No provider confirmation is inferred.

## Ranking

`rank` is read-only and requires a published profile. `mapping` contains exactly
one `{index, state, claim_id}` per stored job requirement. States are supported,
partial, unsupported or unknown. The latter two require a null claim ID; the
others require a current public claim. Direct support additionally requires a
whole-phrase lexical match; this is not semantic verification. `not_applicable`
cannot bypass hard eligibility. Preferred requirements are not yet stored and
use the documented empty-list behavior. A changed profile is read on every call.

`assessment` fields: title_alias_match (boolean/null), seniority_distance (integer
0..20/null), domain (supported/partial/unsupported/unknown), location
(exact/relocation/unclear/mismatch), location_eligible (boolean/null),
candidate_salary and job_salary (salary objects/null), posted_on (YYYY-MM-DD/null),
contact (official/named_recruiter/other/unknown). Optional freshness_window_days
defaults to 30. Salary objects have min, max, currency, basis, period and optional
hours_per_week. See [formulas and assumptions](SCORING.md). Unknowns and unassessed
credibility retain review; explicit location ineligibility yields skip. The
result includes score, confidence, per-component values, requirement matrix and
input fingerprints. It never authorizes an external action or passes draft gates.
