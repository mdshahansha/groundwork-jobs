# Runtime low-level design

| Module | Implemented responsibility | Boundary |
|---|---|---|
| `contracts.py` | Canonical JSON, SHA-256 fingerprints, bounded strings, duplicate-key rejection, aware UTC parsing, typed errors | Does not infer semantic truth |
| `store.py` | Initial schema, foreign keys, WAL transactions, minimal audit | No network or projection files |
| `workspace.py` | Text sources, span claims, immutable corrections, publish gate, job snapshots, logical erasure, manual events | Public claims only enter disclosure views |
| `tasks.py` | Packet/output validation, attempt/deadline caps, isolated review, private export | No model execution or ready export |
| `csv_archive.py` | Byte identity, positional normalization, safe spreadsheet export | No historical application mapping/storage yet |
| `cli.py` | Command schemas, bounded file reads, stable errors | No arbitrary command execution |

Imported source identity is SHA-256 of exact input bytes. Confirmation identity
hashes the corrected claim ID plus replacement text. Claims use Unicode character
offsets into decoded UTF-8 text, excluding an optional BOM. Every factual output
assertion must equal its referenced eligible claim text. This deliberately narrow
rule rejects unsupported additions and numerical changes; it does not implement
semantic entailment or approved paraphrase evaluation.

Profile publication requires name, email, active public evidence and no unresolved
conflict claims. A correction supersedes the old claim and creates a new
candidate-confirmation source with equal sensitivity and an explicit parent link.
Any claim/contact change unpublishes the profile. Re-publication may reuse an
unaffected artifact fingerprint; restricted evidence does not enter that fingerprint.

Task fingerprints include the packet, public evidence, contacts, job snapshot,
policy/prompt/schema/model/template/lens/research/assets/calculation versions and
UTC calculation date. The model version pin currently says `host-unspecified`;
reported host identity is usage metadata, not a verified model pin. A unique
constraint plus `BEGIN IMMEDIATE` makes concurrent equal task requests converge.
Completed outputs are immutable except deliberate privacy erasure. Eligibility
is recalculated before packet access, result submission and private export.
