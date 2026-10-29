# JW-03 disclosure policy

## Owner decision and schema

On 2026-10-29 the owner chose **Keep restricted data out of CVs**. Exceptions
are limited to explicit per-application ATS/referral manual previews.

Provenance and sensitivity remain independent. `document` means source support,
not independently verified employment. `candidate_confirmation` grants no
disclosure permission. Claim sensitivity cannot lower source sensitivity.
Corrections create new sources/claims, retain lineage and sensitivity, copy field
rules, and revoke old grants. Consent never transfers to a corrected claim.

Schema 2 adds `disclosure_rules(claim_id, scopes)` and
`disclosure_consents(id, claim_id, job_id, purpose, recipient, expires_at, binding,
revoked)`. Binding hashes the current claim, source identity/classification,
rules and application context. Audit rows contain only event, opaque ID and time;
denied values and recipient identities are never logged there.

## Permission matrix

| Purpose/channel | Public | Private/restricted | Additional condition |
|---|---|---|---|
| preparation:model | Field rule | Denied | Explicit boolean task consent |
| preparation:local | Field rule | Denied | Shared preparation envelope |
| preparation:export | Field rule | Denied | Existing document gates still apply |
| ats:manual | Denied by default | Denied by default | Rule plus matching application consent |
| referral:manual | Denied by default | Denied by default | Rule plus matching application consent |
| Image or unknown scope | Denied | Denied | No qualified source-image path |

Missing rules default to the three preparation scopes; sensitivity still wins.
Preparation uses their intersection: removing any route removes the field from
all preparation outputs. ATS/referral grants never enter preparation. Reusable
answers do not imply consent. There is no blanket consent or CV exception.

The shared `decision` evaluator in `jw.privacy` filters `Workspace.evidence()`.
Ranking, profile mapping, model/review packets, validated drafts, text/PDF exports
and ZIP handoffs consume this evidence and its current dependency fingerprints.
Removing a field invalidates prepared tasks. Policy-1 tasks become stale on
upgrade. Consent previews separately require exact claim, job, purpose and
recipient, a matching binding, non-revoked consent and a strictly future expiry.

## Images and host-model disclosure

Source images/PDF pages cannot be attached to task or review packets. Binary
images/PDFs are unsupported. SVG/image markup is rejected at import and at egress
for legacy sources. An explicit `media:image` preview is denied even with valid
consent. This is a fail-closed boundary, not OCR or pixel redaction. Generated
PDFs contain filtered literal text only, never imported page images.

Host execution remains manual. `task-create` requires `consent:true` before
`task-packet` emits public evidence, profile name/email and job text. Consent
permits sharing that bounded packet with the user's chosen host, not private or
restricted claims. There is no automatic model dispatch or provider-retention
guarantee. Already copied packets and exports cannot be recalled by revocation.

## Command payloads and synthetic fixtures

`disclosure-rule` takes `{claim_id, scopes}`, for example:

```json
{"claim_id":"clm_fixture","scopes":["ats:manual"]}
```

`disclosure-grant` requires an explicit application binding:

```json
{"claim_id":"clm_fixture","job_id":"job_fixture","purpose":"ats","recipient":"fixture-portal","expires_at":"2026-11-01T00:00:00Z","confirm":true}
```

`disclosure-preview` takes the same claim/job/purpose/recipient plus returned
`consent_id` and optional `media` (text or image). Allowed output contains exact
claim text, `ready:false`, `external_action:false` and an export-retention notice.
Denied output contains only reason/flags, never the value. `disclosure-revoke`
takes `{consent_id}`. Rule changes revoke existing grants, including when the
new rule list equals the previous list. Unknown JSON fields are rejected.

## Migration and rollback

Schema 1 upgrades to 2 in an exclusive transaction, adding tables without
changing sources, claims, links, tasks or outcomes. Failed upgrades roll back
tables and version. Concurrent openers recheck under lock; reopening is idempotent.

Old binaries reject schema 2 rather than silently apply weaker policy. To roll
back a faulty release, stop the application, retain the schema-2 database intact,
and deploy a compatible corrective build. Do not drop rules or reset the schema
version. Restoring an older backup loses later privacy decisions and is not a
supported rollback. Restore-time erasure remains JW-04/JW-13 work. No destructive
contraction occurs in this migration.

## Acceptance evidence

`tests/test_jw_privacy.py` covers correction lineage, ATS/referral exceptions,
wrong application/recipient/purpose, expiry equality, revocation, images, CV
denial, value-free denial logs, packet/review/export/ZIP exclusion, stale outputs,
SVG import/legacy egress, timestamp extremes, migration preservation and rollback.
Existing restriction/PDF tests also remain. JW-03 is implemented for supported
runtime paths; source-image disclosure is explicitly denied, not represented as
supported image redaction. Full provider actions and document quality gates are
separate tickets.

Measured validation: 237 repository tests and 76 independently installed-wheel
workspace tests passed. Runtime version 0.1.4 wheel SHA-256:
`ed7347cc577c71be43c9f005b7b4b22a5effbff88469b3ccbfa8c1463e7be16b`.
