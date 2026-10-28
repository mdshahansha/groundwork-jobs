# CLI contracts, schema version 1

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
| task-create | job_id, kind (`draft_cv`, `draft_letter`, `review`), consent=true | draft_id (required only for review) |
| task-packet, task-resume, draft-export | task_id | None |
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
