# JW-05 semantic checks

Status: implemented for supported runtime paths. Three gates: deterministic guard,
candidate approval, host-model entailment review. None verifies employment facts.

## Rule

A draft assertion is accepted only when its text equals one of:

1. the referenced claim's exact text, or
2. an active paraphrase of that claim that passed the guard, the candidate approved,
   and an independent host-model review judged `entailed`.

Anything else is rejected with `unsupported_assertion`. The message lists guard
reason codes so the host model can repair the wording. It never repeats imported text.

## Guard (`guard-2`, `src/jw/semantics.py`)

`check(claim, paraphrase)` compares lexical invariants:

| Code | Blocks when the paraphrase |
|---|---|
| `quantity_changed` | adds, drops or alters a number, percentage, currency amount, unit or year |
| `entity_added` | adds a capitalized name, acronym or mixed-case token not in the claim |
| `negation_changed` | changes the count of negations (`not`, `no`, `never`, `without`, `n't`, ...) |
| `scope_escalation` | adds seniority, ownership or scope words (`led`, `managed`, `all`, `senior`, ...) |
| `credential_added` | adds credential words (`certified`, `degree`, `completed`, `licensed`, ...) |
| `new_content` | adds any content word, however short, whose five-letter stem is absent from the claim |
| `empty` | contains no words |

Only `new_content` can be acknowledged, and only at approval time
(`acknowledge: ["new_content"]`). All other codes are hard blocks. Passing the guard
is necessary, never sufficient: an unapproved paraphrase is still rejected.

## Entailment review

`paraphrase-approve` returns a fresh packet with only the claim, the wording, no
tools and a closed schema: `verdict` is `entailed`, `not_entailed` or `uncertain`;
`codes` come from `meaning_changed`, `fact_added`, `fact_dropped`, `scope_changed`,
`tense_changed`. `entailed` must carry no codes and every other verdict at least one.
Only `entailed` activates the paraphrase; `uncertain` rejects. Invalid output
consumes one of three attempts, then the paraphrase is `blocked_schema`. A verdict
is immutable. Re-approving revoked wording always requires a new review.

The packet discloses claim text, so `consent: true` is required and only
preparation-eligible (public) claims qualify. Private or restricted claims are refused.

## Lifecycle

- `paraphrase-approve` requires `confirm: true`, `consent: true` and an active claim.
  It stores the guard version and any acknowledged findings.
- Approved paraphrases appear in packets under `evidence[].approved_paraphrases`.
  Approval or revocation changes the dependency fingerprint, so earlier tasks are
  stale and must be recreated.
- Correcting a claim revokes its paraphrases. A rewording of the old claim is not
  support for the corrected one.
- Deleting a source revokes its paraphrases and replaces their text with the opaque ID.
- Paraphrases inherit the claim's sensitivity and disclosure rules. Restricted or
  private claims never reach a packet, so neither do their paraphrases.

## Storage

Schema 3 adds `paraphrases(id, claim_id, text, guard, acknowledged, approved_at,
revoked)` with `UNIQUE(claim_id, text)`. Schema 4 adds `review` (default
`needs_model`) and `review_attempts`. Both upgrades are additive; rows approved under
schema 3 fail closed and stay out of evidence until reviewed.

## Evidence and limits

- `tests/test_jw_semantics.py`: 21 hand-labelled rows plus lifecycle and review tests.
- `tests/fixtures/jw_paraphrase_corpus.json`: 168 synthetic rows, 12 claims, 10 change
  categories and 4 meaning-preserving edits. Labels follow from each edit. guard-2
  catches 120/120 fact-changing rows and blocks 0/48 meaning-preserving rows; the
  test fails if either rate regresses.
- Limits: the guard is lexical, so synonyms it cannot see rely on the candidate and
  the model review. Review quality depends on the host model; tests use synthetic
  verdicts and no real model output was measured.
