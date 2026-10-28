# Runtime architecture: development checkpoint

The maintained target design is [the product HLD](../03-hld.md); release obligations
remain in [the release plan](../05-release-plan.md). This document maps that design
to actual code. It does not claim the target components already exist.

The implemented process is a local Python modular monolith. `jw.cli` accepts
bounded JSON files and returns JSON. `jw.workspace` owns source, claim, profile,
job and outcome operations. `jw.tasks` owns model packet construction and result
validation. Both use `jw.store`, the only persistence layer. SQLite is canonical,
including raw text-source bytes, so there is no database/file dual-write protocol
in this checkpoint. The source package is independently installable through
`pyproject.toml`; the legacy LinkedIn plugin remains independent.

There is no daemon, HTTP listener, browser UI, network fetcher, scheduler or live
provider adapter. External action commands fail before opening a workspace.
The host can request a packet, perform a model call outside this process, and
submit a structured result. Imported instructions never confer tool authority.

Local deployment requires Python 3.11+ and a private, writable directory. SQLite
uses WAL, full synchronization and a ten-second busy timeout. One writer owns a
transaction at a time. Individual connections are not shared between threads.
The test suite creates one connection per concurrent worker.

Remaining target components include PDF/OCR import, semantic mapping, ranking,
sandboxed rendering, quality gates, immutable employer artifacts, protected local
API, provider action ownership, backup recovery and release evaluations. No
unsupported component reports a successful gate or provider receipt.
