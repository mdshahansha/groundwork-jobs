# JW-02 integration feasibility

## 2026-10-29 renderer decision and measured follow-up

The owner approved fixed-template PDFs instead of Docker/custom LaTeX execution.
The Windows ReportLab 4.4.9 path is now implemented and qualified for bounded Latin
private-draft fixtures; see [reproduction and hashes](../architecture/FIXED_RENDERER.md).
CV and letter PDFs were generated, parsed and visually inspected. Seven renderer
tests plus the workspace privacy/staleness test passed. This is a data-only API,
not an OS sandbox, and it does not complete JW-09's full quality gates.

The renderer findings below are the original 2026-10-28 LaTeX investigation and
remain historical evidence; the fixed-backend decision supersedes that selection.
JW-02 remains incomplete because Distilly invocation/output mapping and remaining
integration contract probes have not been executed. Gmail recovery remains
explicitly unresolved with no resend; no live Gmail operation was performed.

Evidence date: **2026-10-28 (Asia/Calcutta)**. Status: **documentation investigation delivered; JW-02 acceptance INCOMPLETE**. This sidecar qualifies the integration assumptions in `docs/03-hld.md`, especially sections 7, 9.3, 11, 12 and ADR-006/008. It does not enable connectors or implement the other tickets.

Only public documentation/source GETs and local source/tool discovery were performed. No mailbox was read, draft created, email sent, credential loaded, provider client instantiated, paid request made, or Distilly code installed/executed. The private review is neither reproduced nor modified. Runtime probes below are specifications, not passing test reports.

## Evidence vocabulary and release disposition

- **Verified documentation/source:** inspected the cited primary source on the evidence date; not a live behavior guarantee.
- **Observed local:** inspected local code or obtained the stated command output.
- **Unverified runtime:** requires an implementation, isolated fixture execution or separately authorized test account.
- **Blocked/unsupported:** expose a reason and fallback, never an empty success result.

| Capability | Evidence and version | Current result | Safe fallback | Release impact |
| --- | --- | --- | --- | --- |
| Gmail remote draft | Gmail REST v1, G1/G2 | Scope documented; runtime unverified | Local text or `.eml` export, candidate reviews and sends | R3 remote draft disabled until authorization and adapter tests pass |
| Gmail direct send / draft send | REST v1, G3/G4 | Different scope requirements; runtime unverified | Candidate sends outside workspace; record manual outcome separately | R3 send disabled |
| Gmail message read / sync | REST v1, G5/G6/G8/G9 | Documented; account and recovery tests unverified | User supplies selected message content and manual outcomes | R2 alert ingestion and R3 tracking cannot claim automatic coverage |
| Gmail lost-response reconciliation | REST v1, G5/G6/G7/G10 | Lookup primitives documented; end-to-end preservation and matching unresolved | Keep `send_unknown`; no automatic resend | Blocks automatic recovery, not R1 preparation |
| Distilly | SHA `0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa`, declared version 1.0.0 | License, entrypoint and documented outputs verified; execution unverified | Built-in evidence extraction and candidate correction; no style enrichment | Optional for R1; fallback integration still needs proof |
| LaTeX/PDF rendering | Windows; Poppler `pdftoppm` 26.07.0 observed | No LaTeX executable found on PATH; full render unverified | Save editable draft with explicit toolchain/quality block | Blocks R1 verified, employer-ready PDF acceptance |
| ATS | HLD handoff boundary | No specific provider submission mechanism verified | Answer sheet plus verified attachments; candidate submits | R4 automated submission unsupported |
| Apify / Publora | Existing local `lib/`, inspected at HEAD `0cf041a68446cf25452d5f3c62f117a2625f8eb2` | Existing interfaces observed; live operation not tested | Paste source text / copy approved comment | Reuse existing package; workspace adapters and safe retries unresolved |

## Gmail: provider permissions versus workspace policy

Scope names below abbreviate `https://www.googleapis.com/auth/`. These are method-specific documented grants, not inspected account credentials.

| Operation | Narrow applicable scope | Other documented scopes | Implication |
| --- | --- | --- | --- |
| `users.drafts.create` | `gmail.compose` | `gmail.modify`, `https://mail.google.com/` | `gmail.send` alone is not listed [G2] |
| `users.messages.send` | `gmail.send` | `gmail.compose`, `gmail.modify`, full mail | Direct raw-message sending can use send-only scope [G3] |
| `users.drafts.send` | `gmail.compose` | `gmail.modify`, full mail | `gmail.send` alone is not listed [G4] |
| `users.messages.list/get` | `gmail.readonly` for message content and search | `gmail.metadata` for metadata; modify/full mail also listed | Neither compose nor send alone enables general mailbox reconciliation [G5/G6] |
| `users.history.list` | `gmail.readonly` for the intended read workflow | `gmail.metadata`, modify/full mail | Metadata-only sync cannot supply bodies for classification [G8] |

Google classifies `gmail.send` as sensitive; compose, readonly and metadata as restricted. Distribution needs a separate consent/verification assessment. There is no general draft-only grant in this documented method set: **compose also authorizes send**. A workspace `draft_only` setting is an application restriction, not a provider-enforced token boundary. Add-on-specific scopes are not a drop-in grant for this local REST client. [G1]

Proposed policy: local preview/export needs no Gmail token. Remote draft creation is an external write requiring its own authorization. For direct send plus reconciliation, obtain independent send and read consent; for remote drafts use compose and disclose its send capability. Enforce action/content/recipient/attachment binding outside model output. Record granted scope evidence separately from local allowed operations. Presence of a connector tool does not establish its token scopes or approval controls.

### Reconciliation: supported lookup, unproven round trip

Gmail accepts base64url MIME in the message `raw` field. That establishes a way to submit headers, not a promise that an arbitrary `X-JW-Action-ID` will survive every draft/edit/send path. No general arbitrary-header search operator was found in the inspected Google references. Do not invent `header:X-JW-Action-ID=...` or treat an action marker as a provider idempotency key. [G10/G7]

The documented search route is `messages.list` with `q=rfc822msgid:<stored-message-id>`; Google explicitly documents that operator. Retrieve each candidate with `messages.get`, using `format=METADATA` and `metadataHeaders` for selected headers, or FULL/RAW when authorized content comparison is needed. `gmail.metadata` does not permit the `q` parameter; readonly permits the intended search path. A metadata-only adapter would need bounded paginated enumeration and per-message header inspection instead. [G5/G6/G7]

Proposed contract, pending adapter and live validation:

1. Before dispatch, persist mailbox/account identity, action ID, generated RFC Message-ID, normalized recipients, approved content and attachment hashes, and attempt time. A custom header is supplementary evidence. Gmail message IDs and RFC Message-IDs are different identifiers.
2. After an ambiguous send response, retain `send_unknown`. If an independently durable provider message ID exists, fetch it. Otherwise search by the stored RFC Message-ID and inspect candidates. An initial SENT filter is useful but must not make missing/deleted labels proof of non-delivery.
3. Require a unique, account-bound match, sent evidence, matching action marker when available, and appropriate content/recipient/attachment checks. MIME transport changes require explicit normalization; raw-byte equality is not assumed. Reused or spoofed Message-IDs, conflicting markers, missing evidence and multiple matches remain unresolved.
4. No match, timeout, expired read consent, incomplete pagination or a scan bound reached is **not** proof that nothing was sent. Return `send_unknown` with a reason and manual review. Never automatically transition to `failed_safe_to_retry` solely from a negative lookup.
5. A matching sent copy can establish provider acceptance, not recipient delivery, application submission or recruiter response. These remain separate events.

This explicitly qualifies HLD section 9.3's `found or not found` branch. Current docs do not establish a send idempotency guarantee or custom-header preservation. Automatic reconciliation remains unresolved without resending.

### History expiry and recovery

History IDs increase but are not contiguous; store them as opaque strings. Google says history is usually retained for at least a week but can expire within hours. An invalid/expired `startHistoryId` can return 404 and requires full synchronization. Process all pages before adopting the final cursor. [G8/G9]

Proposed recovery: mark `resync_required`; preserve existing application/action events; enumerate the configured, consented message window; fetch and upsert by account plus provider message ID; reconcile changes arriving during enumeration from a fresh baseline; commit the rebuilt view/cursor only after complete pagination and durable writes. If that baseline also expires, restart the rebuild. Bounded history coverage must be visible; a recent-window scan cannot claim complete lifetime coverage. Deleted/unrecoverable messages leave explicit evidence gaps. Cursor recovery must never replay an outbound action. This transaction/race handling is a workspace design proposal, not a tested Gmail guarantee.

## Distilly: immutable source inspection

The GitHub commit endpoint for branch `dot-skill` resolved to **`0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa`**, commit timestamp **2026-10-13T05:42:45Z**. The mutable branch was used only for discovery; all file inspection used that full SHA. `package.json` and creator frontmatter declare **1.0.0**. This is an inspected source version, not an installed/tested package or a verified registry release.

- **License verified:** pinned LICENSE is MIT, copyright 2026 titanwings. Preserve its copyright/permission notice with copies or substantial portions. This resolves the repository-license unknown, not rights to input data or every optional dependency. Nothing is vendored here. [D1/D2]
- **Invocation verified in source:** the creator is a host-loaded skill. Pinned instructions describe `$distilly` or `/skills` for Codex and `/distilly` for several other hosts. The Node CLI exposes installation/help/version/package-check operations; it is **not** a `distilly extract --json` inference API. Node metadata requires >=18. Host discovery/runtime behavior was not exercised. [D2/D3/D4]
- **Owner output differs from generated role skills:** the owner flow saves a Markdown profile to `~/.distilly/owner/profile.md` through `tools/owner_profile.py save --profile <file>`. Its always-on linking supports Claude Code and OpenClaw, not Codex at this pin. The other creation families use `tools/skill_writer.py` and document SKILL.md, work.md, persona.md, work_skill.md, persona_skill.md, manifest.json and meta.json under a family/slug directory. These are source-described outputs, not artifacts produced in this investigation. [D5/D6]
- **Adapter implication:** select the owner/profile route for candidate information and map its output into workspace evidence-backed claims. Do not auto-install generated behavioral instructions, auto-link host memory, discover unrelated private sources, or regard a generated profile as verified factual evidence. No stable workspace-compatible structured extraction API was established.
- **Fallback:** when absent, incompatible or declined, explicitly report Distilly unavailable and use built-in extraction over user-selected evidence plus candidate corrections. Keep provenance, unknowns, conflicts and truthfulness gates. Optional style enrichment stays absent. This path is required by the HLD but has not been executed by this sidecar.

## Existing Apify and Publora integration

Source inspection only: `lib/__init__.py`, `lib/backend_selector.py`, `lib/apify_client.py` and `lib/publora_client.py`. No import smoke test was run because importing `lib` invokes environment loading; the task excludes credential access.

Apify already exposes `fetch_post`, `fetch_post_comments`, `fetch_user_recent_comments`, and `fetch_post_engagers`, with a 256-entry, six-hour in-process cache and `force_refresh` option. The convenience `lib.fetch_post(url)` collapses missing configuration and failures to `None`; the workspace must map this to unavailable/paste-required, not a successful empty search. Use the existing client directly when error distinctions are required. Recent comments do not prove recruiter posting history or complete hiring frequency. No keyword-search capability is established by these methods. Actor calls can cost money and were not made.

Publora already exposes comment/reply, reaction, post and reshare operations; `lib.publish` dispatches to Publora/manual/DIY and `lib.repost` resolves the original share parent. Existing client methods also include connection lookup, post lookup and guarded deletion. Do not infer every endpoint mentioned in project prose has a local wrapper: list/update-post methods were not found in this inspected client. Manual results mean handoff only; `None` means unresolved/unavailable; DIY process exit success alone is not a provider receipt. Optional reaction execution is an additional side effect requiring explicit policy, not part of a comment by default.

**Retry blocker:** `PubloraClient._post` retries transient HTTP/network failures. Although it accepts an optional idempotency key, the inspected `create_comment` call does not supply one. Existing retry behavior cannot be assumed compatible with the workspace's no-duplicate contract. Disable workspace live writes until provider idempotency/reconciliation and wrapper behavior are resolved. Reuse the pinned package rather than duplicate its code; correction to that package is outside this file-only task. The client's historical live-verification docstring is not evidence of a live test today.

## Renderer and ATS boundaries

Read-only Windows discovery (`Get-Command latexmk,pdflatex,xelatex,lualatex,pdftoppm,pdftotext -ErrorAction SilentlyContinue`) found only `pdftoppm` among those names. `pdftoppm -v` returned **26.07.0**. `pdftotext -v` failed as command-not-found. This describes PATH availability, not proof that no alternative installation or extraction library exists.

The selected HLD platform is sandboxed LaTeX followed by PDF rasterization and quality checks. A rasterizer version alone does not prove compilation, fonts, text extraction, layout, no-network isolation, resource limits or disabled shell escape. No PDF was built, no screenshot inspected and no sandbox escape probe run. Mark the render gate **INCOMPLETE / toolchain not verified**; preserve editable drafts but do not label them ready or replace visual verification with textual review. Selecting/pinning and exercising a complete Windows renderer remains required before R1 verified export.

ATS remains **handoff-only**. No employer/candidate API access, browser automation mechanism, portal receipt or site permission was tested. Provide an answer sheet and separately verified attachments; let the candidate submit. A click or handoff is not submission evidence. Record manual reports as such, or `submission_unverified` when evidence is insufficient. Site-specific browser assistance requires its own feasibility and authorization work; this report makes no universal claim about ATS API availability.

## Reproducible probes and outstanding acceptance

The source-review commands are read-only. To reproduce the Distilly pin, GET `https://api.github.com/repos/titanwings/distilly/commits/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa`, then inspect the SHA-pinned URLs below. The original branch discovery endpoint was `https://api.github.com/repos/titanwings/distilly/commits/dot-skill`. Local reproduction uses the `Get-Command` and version checks above and reads the named library files. Initial sandbox DNS failed for GitHub; the same public GETs succeeded with network access. No response files were saved.

The following are **pending probe/fixture specifications**, not executable tests added or results obtained. Live steps require a separately authorized synthetic account; they must not run as part of this task.

| Probe | Reproducible scenario | Required result | Current status |
| --- | --- | --- | --- |
| GMAIL-SCOPES | In an isolated account, exercise each matrix operation with only its declared grant; separately verify workspace draft-only policy rejects sends even with compose | Provider scope errors and local authorization errors remain distinguishable | Docs verified; runtime NOT RUN |
| GMAIL-RECONCILE | In an authorized synthetic send test, persist RFC Message-ID and action header; discard a successful send response; list by `rfc822msgid`, get headers/content and match; repeat direct-send and draft-send paths | Unique correct acceptance match without a second send; otherwise `send_unknown` | NOT RUN; header preservation unresolved |
| GMAIL-NEGATIVE | Stub empty search, duplicate Message-ID, missing header, delayed visibility, mismatched mailbox, missing scope and truncated pagination | All ambiguous cases remain unknown; resend call count zero | Fixture specification only |
| GMAIL-HISTORY | Stub paginated history, 404 expiry, full rebuild, concurrent arrival and crash before final cursor commit | No lost/duplicated local events; checkpoint advances only on commit; zero send calls | Fixture specification only; live recovery NOT RUN |
| DISTILLY-PIN | Use isolated checkout at the full SHA; inspect license/version; invoke host with synthetic selected evidence and capture actual output manifest | Declared output mapping, no unrelated source reads or automatic host linking | Source review passed; invocation NOT RUN |
| DISTILLY-ABSENT | Run candidate extraction/correction with dependency unavailable and unsupported source claims | Explicit fallback completes preparation without inventing evidence or bypassing truthfulness gates | NOT RUN; core integration dependency |
| RENDER-WINDOWS | Pin compiler/fonts/rasterizer/extractor; render synthetic Unicode/links/overflow fixtures in no-network, no-shell-escape sandbox; extract and visually inspect all pages | Versioned artifacts and quality results; unsafe input/resource-limit cases blocked | Tool discovery only; end-to-end BLOCKED |
| PROVIDER-FALLBACK | Stub Apify `None`/error, Publora manual/None/DIY, ambiguous write timeout | Explicit unavailable/handoff/unknown outcomes; no false provider receipt or blind retry | Source review only; fixtures NOT RUN |
| ATS-HANDOFF | Export synthetic answer sheet and verified files; inject missing receipt | No submission call; no confirmed submission without supporting evidence | NOT RUN |

Embedded decision records for integration owners:

1. **JW02-D1, proposed:** keep token capabilities and workspace authorization separate; local-only export is the no-token draft fallback.
2. **JW02-D2, safety constraint:** no search result is not proof of send failure; preserve unknown and prohibit blind resend. JW-12/JW-14 need the eventual adapter fixtures.
3. **JW02-D3, proposed:** pin Distilly to the inspected SHA, consume via a host/profile adapter only after fixture validation; use evidence extraction fallback for R1.
4. **JW02-D4, gate:** renderer is not qualified on the observed Windows environment. JW-09 owns complete toolchain and isolation proof.
5. **JW02-D5, boundary:** retain ATS handoff-only and existing Apify/Publora package reuse. No provider implementation is copied here.

**Remaining blockers:** Gmail live round-trip and recovery evidence; tested Distilly invocation/output mapping and absence fallback; complete Windows render/quality/sandbox proof; safe Publora write retry contract; implemented adapter contract fixtures and technical-lead disposition. JW-02 must not be marked fully complete from this document alone. The private ticket status remains untouched by the file-only scope.

## Dated primary-source register

All URLs below were inspected on **2026-10-28**. Google references describe REST **v1**, not a pinned client SDK. Scope/sync pages displayed update date 2026-09-15 and the inspected method pages displayed 2026-04-15 where shown. These are source dates, not test dates.

- G1: [Google Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).
- G2: [Google drafts.create](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create).
- G3: [Google messages.send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send).
- G4: [Google drafts.send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/send).
- G5: [Google messages.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).
- G6: [Google messages.get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get).
- G7: [Google Gmail search operators](https://support.google.com/mail/answer/7190).
- G8: [Google history.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list).
- G9: [Google synchronization and expired history recovery](https://developers.google.com/workspace/gmail/api/guides/sync).
- G10: [Google MIME message sending](https://developers.google.com/workspace/gmail/api/guides/sending).
- D1: [Pinned Distilly MIT license](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/LICENSE).
- D2: [Pinned package metadata](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/package.json).
- D3: [Pinned creator entrypoint](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/SKILL.md).
- D4: [Pinned CLI implementation](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/bin/distilly.mjs).
- D5: [Pinned owner flow](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/prompts/flows/owner.md).
- D6: [Pinned role creation flow](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/prompts/flows/create.md).
- D7: [Pinned install/output guide](https://raw.githubusercontent.com/titanwings/distilly/0afc45c29c360ba7bc8260f1bb0bf34e9155f4fa/INSTALL_EN.md).

Apify/Publora findings above are local implementation observations, not newly verified current vendor promises. Renderer evidence is command output only. No external ATS source is represented as verified.
