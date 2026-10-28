# Errors and recovery

| Error/state | Meaning | Safe recovery |
|---|---|---|
| not_initialized | Missing canonical database | Run init in the intended private directory |
| unsupported_schema | Database version not supported | Use matching software; never downgrade by editing version |
| invalid_json / invalid_schema / invalid_span | Malformed or unexpected input | Correct the payload; rejected model results count toward budget |
| policy_denied | Attempted sensitivity downgrade | Keep restriction; exceptions are unavailable |
| profile_incomplete / profile_conflict / profile_unpublished | Profile not usable | Correct evidence/contacts, resolve conflicts, publish |
| stale_input | Dependencies changed | Materialize a new task; never relabel old output current |
| unknown_claim / unsupported_assertion | Unavailable evidence or altered assertion | Remove the invention or add genuine corrected evidence |
| blocked_schema | Three bad model results | Stop; no implicit reset or unbounded repair |
| blocked_quota / blocked_rate_limit | Reported host limitation | Explicit resume within remaining attempts and deadline |
| blocked_refusal / blocked_timeout | Terminal task failure | Inspect cause; no automatic replay |
| task_expired | Current time is at or after deadline | No submission/export authority is granted |
| source_deleted | Erased content or repeated erased-source import | Do not restore an old database to bypass erasure |
| unsupported_capability | Feature absent or unsafe | Use a separately reviewed manual workflow |
| storage_error | OS/SQLite failure | Check permissions/space/locks; inspect status before retry |

Transactions roll back on exceptions, including interrupted source deletion.
Completed task output survives process restarts. A lost CLI response can be
recovered by inspecting status; identical task creation returns the same ID.
No external action exists, so a local retry cannot send email or applications.
Provider retries and reconciliation are future work, not covered by local
idempotency tests. See the integration feasibility report before building them.
