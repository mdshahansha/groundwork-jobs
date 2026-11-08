# Architecture

Part of the product analysis. Index: [docs/product/README.md](README.md). Status labels: **Implemented** (code and tests in the repo), **Planned** (documented, no code), **Unsupported** (refused on purpose), **Needs Verification** (not proven by a local check).

### 6.1 linkedin-skills

```mermaid
flowchart LR
    U[User in Claude Code or Codex] --> S[Skill instructions<br/>skills/*/SKILL.md]
    S --> R[references/<br/>voice, hooks, precedence]
    S --> L[lib/]
    L --> A[apify_client<br/>read posts, comments, engagers]
    L --> AP[approval gate]
    AP --> P[publora_client<br/>post, comment, reply, reshare]
    L --> X[pixfaro_client<br/>images, quote cards]
    A -. no token .-> M1[User pastes content]
    P -. no key .-> M2[Manual draft to copy]
```

### 6.2 jw lead pipeline

```mermaid
flowchart LR
    subgraph Intake
      N[naukri_mail via gmail.readonly] --> I[leads.py]
      F[himalayas / remoteok feeds] --> I
      LI[LinkedIn post export JSON] --> I
    end
    I --> D[opportunities.ingest<br/>dedup and reposts]
    D --> FL[lead_filter.py<br/>reasons + 0-100 fit]
    FL --> PK[lead-draft-packet]
    PK --> HM[Host model writes e-mail]
    HM --> SB[lead-draft-submit<br/>risk checks: ready or blocked]
    SB --> AP[lead-approve<br/>frozen envelope + resume hash]
    AP --> SD[lead-send<br/>gmail.send, once each]
    SD --> RC[lead-reconcile<br/>Sent folder]
    SD --> MS[mail-sync<br/>bounces, replies]
```

### 6.3 jw command path

```mermaid
sequenceDiagram
    participant C as jw CLI (cli.py)
    participant V as contracts.py
    participant W as Workspace (SQLite, schema 17)
    participant G as Gmail adapter (gmail.py)
    C->>V: parse --input JSON, check required fields
    V-->>C: error JSON on bad input (payload never echoed)
    C->>W: dispatch command in a transaction
    W-->>C: result + audit rows
    C->>G: only lead-fetch, lead-send, lead-reconcile, mail-sync
    C-->>C: print {"ok": ..., "result" | "error"}
```

Deeper design: [HLD](../../docs/architecture/HLD.md), [LLD](../../docs/architecture/LLD.md),
[database](../../docs/architecture/DATABASE_DESIGN.md), [data flow](../../docs/architecture/DATA_FLOW.md),
[security and privacy](../../docs/architecture/SECURITY_AND_PRIVACY.md).
