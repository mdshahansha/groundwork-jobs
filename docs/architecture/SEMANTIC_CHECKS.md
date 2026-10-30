# JW-05 semantic checks

Status: partially implemented. Deterministic guard plus candidate approval. This is
not model-based semantic entailment and does not verify employment facts.

## Rule

A draft assertion is accepted only when its text equals one of:

1. the referenced claim's exact text, or
2. an active paraphrase of that claim that the candidate approved.

Anything else is rejected with `unsupported_assertion`. The message lists guard
reason codes so the host model can repair the wording. It never repeats imported text.

## Guard (`guard-1`, `src/jw/semantics.py`)

`check(claim, paraphrase)` compares lexical invariants:

| Code | Blocks when the paraphrase |
|---|---|
| `quantity_changed` | adds, drops or alters a number, percentage, currency amount, unit or year |
| `entity_added` | adds a capitalized name, acronym or mixed-case token not in the claim |
| `negation_changed` | changes the count of negations (`not`, `no`, `never`, `without`, `n't`, ...) |
| `scope_escalation` | adds seniority, ownership or scope words (`led`, `managed`, `all`, `senior`, ...) |
| `credential_added` | adds credential words (`certified`, `degree`, `completed`, `licensed`, ...) |
| `new_content` | adds a content word whose five-letter stem is absent from the claim |
| `empty` | contains no words |

Only `new_content` can be acknowledged, and only at approval time
(`acknowledge: ["new_content"]`). All other codes are hard blocks. Passing the guard
is necessary, never sufficient: an unapproved paraphrase is still rejected.

## Lifecycle

- `paraphrase-approve` requires `confirm: true` and an active claim. It stores the
  guard version and any acknowledged findings.
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
revoked)` with `UNIQUE(claim_id, text)`. The upgrade from schema 2 is additive.

## Evidence and limits

`tests/test_jw_semantics.py` holds a 21-row labelled synthetic corpus. Every row
that changes a fact fails on at least one hard code. Known limits:

- Short words (three letters or fewer) bypass `new_content`. Approval still gates them.
- Synonyms the guard cannot see may still change meaning. Candidate review is the control.
- No model-based entailment, no measured recall on a real held-out corpus.
