# Security and privacy boundary

This is a development checkpoint for local, single-user use. It is not a hardened
multi-user service. Protect the workspace directory through OS permissions and
disk encryption. The runtime does not encrypt SQLite, manage credentials or
isolate a hostile process running as the same OS user.

Provenance (`document`, `candidate_confirmation`) and sensitivity (`public`,
`private`, `restricted`) are independent. Claims cannot weaken source sensitivity.
Corrections preserve sensitivity and lineage. `disclosable` requires active
public source plus active public claim. The same filtered evidence feeds drafts,
review packets and private export; current dependencies are checked every time.
Candidate confirmation is not independent employment verification.

Contacts are explicitly supplied public presentation fields. Job input must be
a user-selected public listing, not an arbitrary sensitive document. Automatic
sensitive-value detection and field-level exceptions are not implemented.
ATS/referral exceptions cannot be invoked, because those channels do not exist.

Only bounded UTF-8 text is accepted as source content. Binary PDF/archive input
is rejected; HTML remains inert text, with no HTML renderer. No URL is fetched,
shell command executed or source instruction installed. No images are sent to
review, avoiding an unimplemented redaction path. OCR, sandboxed parsers, SSRF
defenses for future fetchers and HTML view escaping remain outstanding.

Source deletion follows correction descendants and erases dependent stored
packets/results. Opaque IDs, hashes and timestamps remain for audit. Exported
copies and model-provider retention cannot be recalled. The deletion API reports
logical erasure, never guaranteed physical erasure. Restore is disabled: copying
an old SQLite file manually is unsupported and can resurrect data.

The source-checkout guard rejects workspace paths inside this application repo.
It does not prove that another chosen directory is private, unsynced or untracked.
No HTTP listener exists, so no CSRF/Host/Origin security implementation is claimed.
Live write adapters remain absent until exact-content approval, fencing, quotas,
suppression, ambiguous-outcome reconciliation and restore safety are complete.
