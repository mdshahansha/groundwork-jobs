"""Versioned JSON command interface; errors never echo imported payloads."""

import argparse
from pathlib import Path
import sqlite3
import sys

from .contracts import MAX_BYTES, WorkspaceError, canonical, fields, parse_json, require, string
from .tasks import Tasks
from .workspace import Workspace

COMMANDS = {
    "disclosure-rule": ({"claim_id", "scopes"}, set()),
    "disclosure-grant": ({"claim_id", "job_id", "purpose", "recipient", "expires_at", "confirm"}, set()),
    "disclosure-revoke": ({"consent_id"}, set()),
    "disclosure-preview": ({"claim_id", "job_id", "purpose", "recipient"}, {"consent_id", "media"}),
    "profile-set": ({"name", "email"}, set()),
    "claim-add": ({"source_id", "start", "end"}, {"sensitivity", "state"}),
    "claim-correct": ({"claim_id", "text"}, set()),
    "paraphrase-check": ({"claim_id", "text"}, set()),
    "paraphrase-approve": ({"claim_id", "text", "confirm", "consent"}, {"acknowledge"}),
    "paraphrase-review-packet": ({"paraphrase_id"}, set()),
    "paraphrase-review-submit": ({"paraphrase_id", "response"}, set()),
    "paraphrase-revoke": ({"paraphrase_id"}, set()),
    "job-add": ({"company", "title", "description", "requirements"},
                {"requisition", "preferred_requirements", "required_authorisations",
                 "mandatory_credentials", "remote_regions", "required_formats", "page_limit"}),
    "policy-set": ({"policy"}, set()),
    "mapping-propose": ({"job_id", "group", "index", "claim_id", "consent"}, set()),
    "mapping-review-packet": ({"mapping_review_id"}, set()),
    "mapping-review-submit": ({"mapping_review_id", "response"}, set()),
    "rank": ({"job_id", "mapping", "assessment"}, {"preferred_mapping"}),
    "rankings": (set(), {"include_outdated"}),
    "task-create": ({"job_id", "kind", "consent"}, {"draft_id", "prepare_anyway"}),
    "post-ingest": ({"post"}, set()),
    "lead-import": ({"source", "path"}, set()),
    "lead-fetch": ({"source"}, {"token_env", "days", "limit"}),
    "lead-filter": (set(), {"policy", "applied_path", "export_path", "now", "limit"}),
    "lead-draft-packet": ({"post_id", "facts_path"}, set()),
    "lead-draft-submit": ({"post_id", "subject", "body", "facts_path", "candidate"}, set()),
    "lead-drafts": (set(), {"state"}),
    "lead-approve": ({"draft_ids", "resume_path"}, {"hours"}),
    "lead-send": ({"resume_path"}, {"token_env", "limit"}),
    "lead-reconcile": (set(), {"token_env"}),
    "merge-decide": ({"merge_id", "accept"}, set()),
    "merge-undo": ({"merge_id"}, set()),
    "opportunities": (set(), {"cursor", "limit"}),
    "usage-report": ({"job_id"}, set()),
    "extraction-create": ({"source_id", "consent"}, set()),
    "extraction-packet": ({"extraction_id"}, set()),
    "extraction-submit": ({"extraction_id", "response"}, set()),
    "extraction-proposals": ({"extraction_id"}, set()),
    "extraction-accept": ({"extraction_id", "indices", "confirm"}, set()),
    "task-packet": ({"task_id"}, set()),
    "task-submit": ({"task_id", "response"}, set()),
    "task-failure": ({"task_id", "reason"}, set()),
    "task-resume": ({"task_id"}, set()),
    "draft-export": ({"task_id"}, set()),
    "draft-render": ({"task_id", "output_path"}, set()),
    "draft-verify": ({"task_id"}, set()),
    "render-font": (set(), {"path"}),
    "draft-readiness": ({"task_id"}, set()),
    "mail-sync": ({"transport"}, {"path", "token_env", "scopes", "budget", "allowed"}),
    "mail-review": (set(), set()),
    "profile-map": ({"job_id", "markdown"}, set()),
    "handoff-preview": ({"cv_task_id", "letter_task_id", "output_path"}, set()),
    "delete-preview": ({"source_id"}, set()),
    "source-delete": ({"source_id", "confirm"}, set()),
    "outcome-record": ({"job_id", "kind", "effective_at"}, set()),
    "backup": (set(), {"to"}),
    "model-pin": ({"model"}, set()),
    "history-import": ({"path", "mapping"}, set()),
    "history-show": ({"import_id"}, set()),
    "history-export": ({"import_id", "output_path"}, set()),
    "schedule-set": ({"policy"}, set()),
    "schedule-next": ({"channel"}, set()),
    "suppress": ({"address", "reason"}, {"company"}),
    "metrics": (set(), set()),
    "activity-record": ({"job_id", "event"}, {"run_id"}),
    "activity-time": ({"job_id"}, set()),
    "pause": (set(), set()),
    "resume": ({"holder"}, {"seconds"}),
    "checkpoint": (set(), set()),
    "application-state": ({"job_id"}, set()),
    "rankings-refresh": (set(), set()),
    "restore": ({"backup", "confirm"}, set()),
}
UNSUPPORTED = {"ready-export", "send", "ats-submit", "capture", "schedule"}


def read_bounded(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "input_too_large", "Input exceeds byte limit.")
    return data


def dispatch(ws, command, data):
    tasks = Tasks(ws)
    if command in COMMANDS:
        fields(data, *COMMANDS[command])
    if command.startswith("disclosure-"):
        from .privacy import Privacy
        policy = Privacy(ws)
        action = {"disclosure-rule": policy.set_rule, "disclosure-grant": policy.grant,
                  "disclosure-revoke": policy.revoke, "disclosure-preview": policy.preview}[command]
        return action(**data)
    if command == "profile-set":
        return ws.set_profile(**data)
    if command == "profile-publish":
        return ws.publish_profile()
    if command == "claim-add":
        return ws.add_claim(**data)
    if command == "claim-correct":
        return ws.correct_claim(**data)
    if command == "paraphrase-check":
        from .semantics import check
        string(data["text"], 2000)
        return check(ws.store.one("claims", data["claim_id"])["text"], data["text"])
    if command == "paraphrase-approve":
        return ws.approve_paraphrase(data["claim_id"], data["text"], data["confirm"],
                                     data.get("acknowledge", []), data["consent"])
    if command == "paraphrase-review-packet":
        return ws.paraphrase_packet(data["paraphrase_id"])
    if command == "paraphrase-review-submit":
        return ws.submit_paraphrase_review(data["paraphrase_id"], canonical(data["response"]).encode())
    if command == "paraphrase-revoke":
        return ws.revoke_paraphrase(data["paraphrase_id"])
    if command == "job-add":
        return ws.add_job(data)
    if command == "policy-set":
        return ws.set_policy(data["policy"])
    if command == "policy-show":
        policy, policy_hash = ws.active_policy()
        return {"policy_hash": policy_hash, "policy": policy}
    if command == "mapping-propose":
        return ws.propose_mapping(**data)
    if command == "mapping-review-packet":
        return ws.mapping_packet(data["mapping_review_id"])
    if command == "mapping-review-submit":
        return ws.submit_mapping_review(data["mapping_review_id"], canonical(data["response"]).encode())
    if command == "rank":
        return ws.rank(**data)
    if command == "rankings":
        require(data.get("include_outdated", False) in (True, False), "invalid_schema", "Expected a boolean.")
        return ws.rankings(data.get("include_outdated", False))
    if command == "task-create":
        return tasks.create(**data)
    if command == "usage-report":
        return tasks.usage_report(**data)
    if command == "extraction-create":
        return tasks.extraction_create(**data)
    if command == "extraction-packet":
        return tasks.extraction_packet(**data)
    if command == "extraction-submit":
        return tasks.extraction_submit(data["extraction_id"], canonical(data["response"]).encode())
    if command == "extraction-proposals":
        return tasks.extraction_proposals(**data)
    if command == "extraction-accept":
        return tasks.extraction_accept(**data)
    if command == "task-packet":
        return tasks.packet(**data)
    if command == "task-submit":
        return tasks.submit(data["task_id"], canonical(data["response"]).encode())
    if command == "task-failure":
        return tasks.report_failure(**data)
    if command == "task-resume":
        return tasks.resume(**data)
    if command == "draft-export":
        return tasks.private_export(**data)
    if command in ("mail-sync", "mail-review"):
        from .actions import Actions
        from .execution import Executor
        from .gmail import GmailAdapter, transport
        from .mailsync import MailSync
        executor = Executor(Actions(ws))
        if command == "mail-review":
            return {"review": MailSync(executor).review_queue()}
        allowed = data.get("allowed", ["read"])
        require(isinstance(allowed, list) and set(allowed) <= {"read", "label"}, "invalid_schema",
                "mail-sync allows read and label only; sending stays unsupported here.")
        return GmailAdapter(executor, transport(data), budget=data.get("budget", 5000), allowed=allowed).sync()
    if command == "draft-readiness":
        from .visual import readiness
        return readiness(tasks, data["task_id"])
    if command == "draft-verify":
        return tasks.verify_draft(**data)
    if command == "draft-render":
        return tasks.render_private(**data)
    if command == "render-font":
        return tasks.set_render_font(data.get("path"))
    if command == "profile-map":
        from .integrations import map_profile
        with ws.store.transaction():
            return map_profile(data["markdown"], ws.dependencies(data["job_id"])["evidence"])
    if command == "handoff-preview":
        return tasks.handoff_preview(**data)
    if command == "delete-preview":
        return ws.deletion_preview(**data)
    if command == "source-delete":
        require(data["confirm"] is True, "confirmation_required", "Preview deletion and explicitly confirm.")
        return ws.delete_source(data["source_id"])
    if command == "outcome-record":
        return ws.record_outcome(**data)
    if command.startswith("history-"):
        from . import history
        if command == "history-import":
            string(data["path"], 4096)
            return history.import_history(ws, read_bounded(data["path"]), data["mapping"])
        if command == "history-show":
            return history.history(ws, data["import_id"])
        string(data["output_path"], 4096)
        body = history.export_history(ws, data["import_id"])
        with Path(data["output_path"]).open("xb") as stream:
            stream.write(body)
        return {"output_path": data["output_path"], "bytes": len(body)}
    if command.startswith("schedule-"):
        from .schedule import Schedule
        schedule = Schedule(ws)
        if command == "schedule-set":
            return schedule.set_policy(data["policy"])
        string(data["channel"], 20)
        waiting = schedule.check(data["channel"])
        return {"channel": data["channel"], "now": waiting is None,
                "reason": waiting[0] if waiting else None, "next": waiting[2] if waiting else None}
    if command in ("lead-approve", "lead-send", "lead-reconcile"):
        from . import lead_queue
        if command == "lead-approve":
            return lead_queue.approve(ws, data["draft_ids"], data["resume_path"], data.get("hours", 24))
        from .gmail import transport
        scopes = ["gmail.send"] if command == "lead-send" else ["gmail.readonly"]
        gmail = transport({"transport": "http", "token_env": data.get("token_env", "JW_GMAIL_SEND_TOKEN"),
                           "scopes": scopes})
        if command == "lead-send":
            return lead_queue.send(ws, gmail, data["resume_path"], data.get("limit", 20))
        return lead_queue.reconcile(ws, gmail)
    if command.startswith("lead-draft"):
        from . import lead_drafts
        if command == "lead-draft-packet":
            return lead_drafts.packet(ws, data["post_id"], data["facts_path"])
        if command == "lead-draft-submit":
            return lead_drafts.submit(ws, data["post_id"], data["subject"], data["body"], data["facts_path"],
                                      data["candidate"])
        return {"drafts": lead_drafts.drafts(ws, data.get("state"))}
    if command == "lead-filter":
        from datetime import datetime
        from . import lead_filter
        applied = lead_filter.applied_from_tracker(data["applied_path"]) if data.get("applied_path") else ()
        now = datetime.fromisoformat(data["now"]) if data.get("now") else None
        result = lead_filter.screen(ws, data.get("policy"), applied, now)
        if data.get("export_path"):
            import csv
            columns = ["fit", "title", "company", "location", "posted_at", "min_years", "contact_email", "url",
                       "matched_skills", "poster_posts_seen_30d", "checks_pending", "provider", "post_id"]
            with Path(data["export_path"]).open("x", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for lead in result["leads"]:
                    writer.writerow(dict(lead, matched_skills=" ".join(lead["matched_skills"]),
                                         checks_pending=" ".join(lead["checks_pending"])))
            result["exported"] = data["export_path"]
        result["leads"] = result["leads"][:data.get("limit", 50)]
        return result
    if command in ("lead-import", "lead-fetch"):
        from . import leads
        if command == "lead-import":
            items = parse_json(Path(data["path"]).read_text(encoding="utf-8"), limit=64 * 1024 * 1024)
            return leads.import_leads(ws, data["source"], items)
        if data["source"] == "naukri_mail":
            from .gmail import transport
            gmail = transport({"transport": "http", "token_env": data.get("token_env", "JW_GMAIL_TOKEN"),
                               "scopes": ["gmail.readonly"]})
            items = leads.fetch_naukri_invites(gmail, data.get("days", 7), data.get("limit", 100))
        else:
            items = leads.fetch_feed(data["source"])
        return leads.import_leads(ws, data["source"], items)
    if command in ("post-ingest", "merge-decide", "merge-undo", "opportunities"):
        from .opportunities import Opportunities
        opps = Opportunities(ws)
        if command == "post-ingest":
            return opps.ingest(data["post"])
        if command == "merge-decide":
            return opps.decide(data["merge_id"], data["accept"])
        if command == "merge-undo":
            return opps.unmerge(data["merge_id"])
        return opps.page(data.get("cursor"), data.get("limit", 20))
    if command in ("metrics", "activity-record", "activity-time"):
        from . import metrics
        if command == "metrics":
            return metrics.report(ws)
        if command == "activity-record":
            return metrics.record_activity(ws, data["job_id"], data["event"], data.get("run_id"))
        return metrics.active_time(ws, data["job_id"])
    if command == "suppress":
        from .suppression import suppress
        return suppress(ws, data["address"], data["reason"], data.get("company"))
    if command in ("pause", "resume", "checkpoint"):
        from .actions import Actions
        from .execution import Executor
        from .runs import Runs
        runs = Runs(Executor(Actions(ws)))
        return {"pause": runs.pause, "resume": runs.resume, "checkpoint": runs.checkpoint}[command](**data)
    if command == "application-state":
        from .runs import reduce_application
        return reduce_application(ws, data["job_id"])
    if command == "model-pin":
        return ws.pin_model(data["model"])
    if command == "rankings-refresh":
        return ws.refresh_rankings()
    if command == "backup":
        from .backup import backup
        return backup(ws, data.get("to"))
    if command == "schema":
        from .traceability import command_schemas
        return command_schemas()
    return ws.status()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local job workspace (development checkpoint; no external actions)")
    parser.add_argument("--workspace", required=True, help="Private directory outside the application source checkout")
    parser.add_argument("command", choices=sorted(set(COMMANDS) | UNSUPPORTED |
                                                {"init", "status", "schema", "source-import", "archive-import", "profile-publish", "policy-show"}))
    parser.add_argument("--input", help="UTF-8 JSON request file; raw UTF-8 text for source-import")
    parser.add_argument("--sensitivity", choices=["public", "private", "restricted"], default="private")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run on a throwaway copy and report the effects; the workspace is unchanged")
    parser.add_argument("--provenance", choices=["document", "candidate_confirmation"], default="document")
    args = parser.parse_args(argv)
    ws = None
    try:
        require(args.command not in UNSUPPORTED, "unsupported_capability",
                "Capability is disabled; no external action or ready export occurred.")
        needs_input = args.command in COMMANDS or args.command in ("source-import", "archive-import")
        require(bool(args.input) == needs_input, "invalid_arguments", "Provide --input only for commands requiring payloads.")
        raw = read_bounded(args.input) if needs_input else None
        if args.dry_run:
            from .simulation import run
            require(args.command not in ("init",), "invalid_arguments", "init has nothing to simulate.")
            if args.command == "restore":
                from .backup import _manifest
                data = parse_json(raw)
                fields(data, *COMMANDS["restore"])
                string(data["backup"], 4096)
                manifest = _manifest(data["backup"])
                result = {"simulated": True, "result": {"valid": True, "schema_version": manifest["schema_version"]},
                          "effects": {"rows": {}, "audit": [], "files": [], "external_actions": []}}
            elif args.command == "archive-import":
                result = run(args.workspace, args.command, {"raw": raw}, lambda w, c, d: w.import_archive(
                    d["raw"], provenance=args.provenance, sensitivity=args.sensitivity))
            elif args.command == "source-import":
                result = run(args.workspace, args.command, {"raw": raw}, lambda w, c, d: w.import_source(
                    d["raw"], provenance=args.provenance, sensitivity=args.sensitivity))
            else:
                result = run(args.workspace, args.command, parse_json(raw) if raw is not None else {}, dispatch)
            print(canonical({"ok": True, "result": result}))
            return 0
        if args.command == "restore":
            # The live database is replaced, so no connection may stay open.
            from .backup import restore
            data = parse_json(raw)
            fields(data, *COMMANDS["restore"])
            require(data["confirm"] is True, "confirmation_required", "Restore replaces workspace data; confirm.")
            string(data["backup"], 4096)
            print(canonical({"ok": True, "result": restore(args.workspace, data["backup"])}))
            return 0
        ws = Workspace(args.workspace, create=args.command == "init")
        if args.command == "archive-import":
            result = ws.import_archive(raw, provenance=args.provenance, sensitivity=args.sensitivity)
        elif args.command == "source-import":
            result = ws.import_source(raw, provenance=args.provenance, sensitivity=args.sensitivity)
        else:
            result = dispatch(ws, args.command, parse_json(raw) if raw is not None else {})
        print(canonical({"ok": True, "result": result}))
        return 0
    except WorkspaceError as exc:
        print(canonical({"ok": False, "error": {"code": exc.code, "message": str(exc)}}))
        return 2
    except (OSError, sqlite3.Error):
        print(canonical({"ok": False, "error": {"code": "storage_error",
              "message": "Storage operation failed; check permissions, disk space and workspace locks."}}))
        return 3
    finally:
        if ws:
            ws.close()


if __name__ == "__main__":
    sys.exit(main())
