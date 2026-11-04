# Deterministic ranking contract: calculations@2, ranking-policy@1

This is the technical completion of previously unspecified arithmetic, not
product-approved calibration. PRD weights remain 35/15/10/10/10/10/5/5 (`weights@1`).
The CLI accepts explicit candidate assessments; no model or keyword extractor is
trusted to infer hard eligibility. Calibration (FR-RNK-05) and stretch roles
(FR-RNK-06) remain open.

All arithmetic uses Decimal, rounds once to two decimals with ROUND_HALF_UP,
and stays within 0..100. Score is relevance, not hiring probability or ATS score.
Confidence is the weighted fraction of known component inputs, not probability.
Ties use ascending immutable job ID. Unknowns alone never hard-exclude.

| Component | Formula |
|---|---|
| Required / preferred skills | Separate means over the job's required and preferred requirements: supported=1, partial=0.5, unsupported=0, unknown=0.25; empty list=0.5 with zero confidence |
| Title/seniority | Alias mismatch=0; alias match with distance 0/1/2+=1/0.5/0; incomplete input=0.5, unknown |
| Domain | supported=1, partial=0.5, unsupported=0, unknown=0.5 |
| Location | exact=1, relocation=0.6, unclear=0.5, mismatch=0; explicit ineligible always excludes |
| Salary | Comparable ranges: intersection width divided by candidate range width, clipped to 0..1; point expectation scores 1 if inside job range; incomparable=0.5, unknown |
| Freshness | max(0, 1-age_days/policy.freshness.max_age_days); absent or future date=0.5, unknown |
| Contact | official=1, named_recruiter=0.6, other=0.3, unknown=0.5 |

Salary comparison requires equal currency and pay basis (base, ctc or total).
No currency conversion or basis equivalence is assumed. Monthly pay multiplies
by 12; annual pay is unchanged. Hourly pay requires explicit hours/week, then
multiplies by hours/week and 52. Unknown hourly hours means incomparable.
Amounts must be finite, nonnegative, ordered, at most one billion, and have
numeric exponents within -12..12. Calculations use a private 28-digit Decimal
context, unaffected by the caller's ambient settings. These calculations
do not establish salary eligibility or promise an offer.

Experience counts the union of half-open intervals, never overlapping days twice.
Exact dates denote boundaries. For month-only dates the conservative start is
that month's last day and the conservative end is its first day. Open end means
the explicitly supplied calculation date. Clip at that date, count nonnegative
days, and divide by 365.25 with rounding down to two decimals. Min/max experience
is reported separately as below/within/above/unknown; it is not a ninth weighted
component and does not silently exclude a candidate.

## Ranking policy (FR-CFG-01 ranking subset, FR-CFG-02)

`policy-set` validates a closed `ranking-policy@1` object. Unknown keys fail with
`policy_invalid`, the field path and a closest-match suggestion; an invalid edit
leaves the previous policy active. Lists are trimmed, whitespace-collapsed,
casefolded (country codes stay uppercase), deduplicated and sorted before the
SHA-256 hash, so equivalent policies share one `pol_…` hash. There is no default
policy: `rank` fails with `policy_missing` until one is set.

| Key | Validation |
|---|---|
| `schema` | `ranking-policy@1` |
| `weights` | `weights@1`. `weights@0` (legacy job-skill set) is refused: it needs experience and education components calculations@2 does not compute |
| `relevance_threshold` | integer 0..100 |
| `freshness.max_age_days` | integer 1..90 |
| `companies.deny`, `skills.excluded_terms` | at most 200 strings of at most 200 characters |
| `location.countries`, `location.remote` | ISO 3166-1 alpha-2 codes; `only`/`allowed`/`no`; a country is needed when remote is `no` |
| `eligibility.country` | candidate's ISO country or null (unknown) |
| `eligibility.authorisations_not_held`, `eligibility.credentials_absent` | the candidate's explicit statements; absence of an entry is unknown, not held |
| `history.exclude_applied_within_days` | integer 0..365; 0 disables |

Each ranking stores the policy hash that produced it. Activating a different
policy marks every current ranking `outdated` (rows are kept). Re-ranking a job
marks its previous ranking outdated. Deleting a source marks all current
rankings outdated because their evidence may be gone. `rankings` lists the
current shortlist (eligible by score, excluded after) and, on request, outdated
rows with their pinned hash.

## Hard constraints (FR-RNK-01)

Every exclusion carries `{code, rule, value}`. Matching is casefolded and
whitespace-normalised; excluded terms are whole phrases.

| Code | Fires only when |
|---|---|
| `LOCATION_MISMATCH` | assessment `location_eligible` is explicitly false |
| `COMPANY_DENIED` | job company equals a `companies.deny` entry |
| `EXCLUDED_TERM` | a term occurs in the title, required or preferred requirements |
| `REMOTE_REGION_MISMATCH` | the job states `remote_regions` and the candidate country is known and absent |
| `AUTHORISATION_NOT_HELD` | a job `required_authorisations` entry is in `authorisations_not_held` |
| `MANDATORY_CREDENTIAL_MISSING` | a job `mandatory_credentials` entry is in `credentials_absent` |
| `ALREADY_APPLIED` | a manual `manual_applied` outcome is younger than the history window |
| `CREDIBILITY_BLOCKED` | not reachable in R1: credibility is always `unassessed` |

## Requirement matrix and semantic mapping (FR-RNK-03)

`rank` takes one mapping per stored required requirement and, when the job has
`preferred_requirements`, `preferred_mapping` with one entry per preferred one.
Each matrix row records its group, index, state, claim ID and evidence label.

- `supported` needs a current preparation-eligible claim and either a
  whole-phrase occurrence of the requirement in the claim or one of its entailed
  paraphrases (label `lexical`), or a `direct` host-model mapping review for that
  exact job, group, index and claim (label `model_reviewed_direct`).
- `partial` cites a current claim and is labelled `related`. It never becomes
  supported; a `related` review does not unlock `supported`.
- `unknown` and `unsupported` cite no claim. `not_applicable` is not accepted.

`mapping-propose` (explicit consent; claim must be preparation-eligible) opens a
fresh packet holding only the requirement, the claim text and a closed schema:
`direct|related|none|uncertain` with codes `transferable_only`, `different_skill`,
`insufficient_detail`, `scope_mismatch`. `direct` needs no codes; every other
verdict needs one. Invalid output consumes one of three attempts, then the review
is `blocked_schema`. Verdicts are immutable. A correction creates a new claim ID,
so an old verdict never transfers; deleting the source revokes its reviews.
The model verdict is a semantic check, not employment verification.

## Recommendation (FR-RNK-04)

Hard exclusions give `skip` with codes. A score below `relevance_threshold` gives
`skip` with `below_threshold`. Otherwise the result is `review` with reasons
`credibility_unassessed`, `availability_unverified` and, when confidence is below
50, `many_unknowns`. R1 has no credibility engine, so `prepare` is not emitted;
the candidate may still choose local preparation explicitly. `gaps` lists every
component below full value or full confidence, heaviest weight first, so a
missing salary appears as a gap and never hides the job (US-RNK-03).
