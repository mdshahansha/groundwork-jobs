"""Versioned JSON command interface; errors never echo imported payloads."""

import argparse
from pathlib import Path
import sqlite3
import sys

from .contracts import MAX_BYTES, WorkspaceError, canonical, fields, parse_json, require
from .tasks import Tasks
from .workspace import Workspace

COMMANDS = {
    "profile-set": ({"name", "email"}, set()),
    "claim-add": ({"source_id", "start", "end"}, {"sensitivity", "state"}),
    "claim-correct": ({"claim_id", "text"}, set()),
    "job-add": ({"company", "title", "description", "requirements"}, {"requisition"}),
    "rank": ({"job_id", "mapping", "assessment"}, set()),
    "task-create": ({"job_id", "kind", "consent"}, {"draft_id"}),
    "task-packet": ({"task_id"}, set()),
    "task-submit": ({"task_id", "response"}, set()),
    "task-failure": ({"task_id", "reason"}, set()),
    "task-resume": ({"task_id"}, set()),
    "draft-export": ({"task_id"}, set()),
    "draft-render": ({"task_id", "output_path"}, set()),
    "delete-preview": ({"source_id"}, set()),
    "source-delete": ({"source_id", "confirm"}, set()),
    "outcome-record": ({"job_id", "kind", "effective_at"}, set()),
}
UNSUPPORTED = {"ready-export", "send", "ats-submit", "capture", "restore", "schedule"}


def read_bounded(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "input_too_large", "Input exceeds byte limit.")
    return data


def dispatch(ws, command, data):
    tasks = Tasks(ws)
    if command in COMMANDS:
        fields(data, *COMMANDS[command])
    if command == "profile-set":
        return ws.set_profile(**data)
    if command == "profile-publish":
        return ws.publish_profile()
    if command == "claim-add":
        return ws.add_claim(**data)
    if command == "claim-correct":
        return ws.correct_claim(**data)
    if command == "job-add":
        return ws.add_job(data)
    if command == "rank":
        return ws.rank(**data)
    if command == "task-create":
        return tasks.create(**data)
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
    if command == "draft-render":
        return tasks.render_private(**data)
    if command == "delete-preview":
        return ws.deletion_preview(**data)
    if command == "source-delete":
        require(data["confirm"] is True, "confirmation_required", "Preview deletion and explicitly confirm.")
        return ws.delete_source(data["source_id"])
    if command == "outcome-record":
        return ws.record_outcome(**data)
    return ws.status()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local job workspace (development checkpoint; no external actions)")
    parser.add_argument("--workspace", required=True, help="Private directory outside the application source checkout")
    parser.add_argument("command", choices=sorted(set(COMMANDS) | UNSUPPORTED |
                                                {"init", "status", "source-import", "profile-publish"}))
    parser.add_argument("--input", help="UTF-8 JSON request file; raw UTF-8 text for source-import")
    parser.add_argument("--sensitivity", choices=["public", "private", "restricted"], default="private")
    parser.add_argument("--provenance", choices=["document", "candidate_confirmation"], default="document")
    args = parser.parse_args(argv)
    ws = None
    try:
        require(args.command not in UNSUPPORTED, "unsupported_capability",
                "Capability is disabled; no external action or ready export occurred.")
        needs_input = args.command in COMMANDS or args.command == "source-import"
        require(bool(args.input) == needs_input, "invalid_arguments", "Provide --input only for commands requiring payloads.")
        raw = read_bounded(args.input) if needs_input else None
        ws = Workspace(args.workspace, create=args.command == "init")
        if args.command == "source-import":
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
