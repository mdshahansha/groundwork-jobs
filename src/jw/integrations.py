"""Conservative integration qualification boundaries; no write transport."""

from .contracts import fields, require, string


def map_profile(markdown, evidence):
    """Map complete Markdown lines to selected claims; never import instructions.

    This consumes a manually supplied Distilly owner profile, not a fabricated
    structured Distilly API. Unsupported prose remains unassessed.
    """
    string(markdown, 64000)
    by_text = {}
    for claim in evidence:
        by_text.setdefault(claim["text"], []).append(claim["claim_id"])
    mapped, unassessed = [], 0
    for line in markdown.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith(("- ", "* ")):
            text = text[2:]
        matches = by_text.get(text, [])
        if len(matches) == 1:
            item = {"text": text, "claim_id": matches[0]}
            if item not in mapped:
                mapped.append(item)
        else:
            unassessed += 1
    return {"assertions": mapped, "unassessed_lines": unassessed,
            "ready": False, "instructions_executed": False}


def source_result(result):
    """Legacy fetch_post(None) is unavailable, never successful empty discovery."""
    if not isinstance(result, dict) or not result:
        return {"state": "unavailable", "fallback": "paste_source"}
    return {"state": "unverified_source", "data": result}


def write_result(result):
    """A wrapper result alone cannot prove provider acceptance."""
    if isinstance(result, dict) and result.get("mode") == "manual":
        return {"state": "handoff", "provider_confirmed": False}
    return {"state": "unknown", "provider_confirmed": False, "retry_allowed": False}


def gmail_permission(operation, scopes, allowed_operations):
    """Provider grants and workspace consent are independent gates."""
    grants = {
        "draft": {"gmail.compose", "gmail.modify", "https://mail.google.com/"},
        "send": {"gmail.send", "gmail.compose", "gmail.modify", "https://mail.google.com/"},
        "draft_send": {"gmail.compose", "gmail.modify", "https://mail.google.com/"},
        "read": {"gmail.readonly", "gmail.modify", "https://mail.google.com/"},
    }
    require(operation in grants, "unsupported_capability", "Unknown Gmail operation.")
    require(operation in allowed_operations, "policy_denied", "Operation is not authorized locally.")
    normalized = {s.removeprefix("https://www.googleapis.com/auth/") for s in scopes}
    require(bool(normalized & grants[operation]), "missing_scope", "Required provider grant is absent.")


def reconcile_send(expected, candidates, complete=False):
    """Evaluate normalized adapter evidence. Never dispatch or permit a resend.

    Transport must independently establish account, sent status and normalized
    content hashes. Caller-supplied records are not live provider proof.
    """
    keys = {"account", "message_id", "recipients_hash", "content_hash", "attachments_hash"}
    fields(expected, keys)
    for value in expected.values():
        string(value)
    unknown = {"state": "send_unknown", "retry_allowed": False}
    if complete is not True or not isinstance(candidates, list) or len(candidates) != 1:
        return unknown
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("sent") is not True:
        return unknown
    if any(candidate.get(key) != expected[key] for key in keys):
        return unknown
    # A qualified live adapter is still required before canonical confirmation.
    return {"state": "matched_evidence", "provider_confirmed": False, "retry_allowed": False}


def collect_history(fetch_page, cursor, max_pages=100):
    """Stage a complete bounded history batch; never advance durable cursors.

    The future transport/store adapter must commit changes and cursor together.
    Exceptions, expired history and pagination loops yield no partial batch.
    """
    string(cursor)
    require(type(max_pages) is int and 1 <= max_pages <= 100,
            "invalid_schema", "History page budget must be 1..100.")
    token, seen, changes = None, set(), {}
    for _ in range(max_pages):
        page = fetch_page(cursor, token)
        fields(page, {"historyId"}, {"history", "nextPageToken"})
        string(page["historyId"])
        history = page.get("history", [])
        require(isinstance(history, list), "invalid_schema", "History must be a list.")
        for event in history:
            require(isinstance(event, dict) and isinstance(event.get("id"), str),
                    "invalid_schema", "History event requires an ID.")
            previous = changes.get(event["id"])
            require(previous is None or previous == event, "history_conflict", "Conflicting history event.")
            changes[event["id"]] = event
            require(len(changes) <= 10000, "history_limit", "History batch exceeds limit.")
        token = page.get("nextPageToken")
        if token is None:
            return {"cursor": page["historyId"], "history": list(changes.values())}
        string(token)
        require(token not in seen, "history_loop", "Repeated pagination token.")
        seen.add(token)
    require(False, "history_limit", "History page budget exhausted.")
