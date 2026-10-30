"""Strict wire values shared by the CLI, store and model-task boundary."""

from datetime import datetime, timezone
import hashlib
import json
import re

MAX_BYTES = 1_000_000
MAX_PACKET_BYTES = 64_000
SENSITIVITY = {"public", "private", "restricted"}
PROVENANCE = {"document", "candidate_confirmation"}
TASK_KINDS = {"draft_cv", "draft_letter", "review"}
VERSIONS = {"schema": "3", "prompt": "1", "policy": "2", "semantic": "guard-1", "template": "text-1",
            "assets": "none", "lens": "neutral-1", "research": "unavailable",
            "calculation": "1", "model": "host-unspecified"}


class WorkspaceError(Exception):
    """Stable public error; messages contain no imported document text."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise WorkspaceError(code, message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                "invalid_time", "Timestamp requires a UTC offset.")
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise WorkspaceError("invalid_time", "Use an ISO-8601 timestamp with offset.") from None


def image_markup(text):
    """Unsupported textual image containers are never qualified plain evidence."""
    return bool(re.search(r"<\s*(?:[\w-]+:)?(?:svg|img|image)\b|data\s*:\s*image/", text, re.I))


def fields(value, required, optional=()):
    require(isinstance(value, dict), "invalid_schema", "Expected an object.")
    require(set(required) <= value.keys() <= set(required) | set(optional),
            "invalid_schema", "Missing or unknown fields.")


def string(value, maximum=2000):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(c) < 32 and c not in "\n\t" for c in value),
            "invalid_schema", "Expected bounded, non-empty text without control characters.")
    return value


def parse_json(raw, limit=MAX_BYTES):
    require(len(raw) <= limit, "input_too_large", "Input exceeds the byte limit.")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "invalid_schema", "Duplicate JSON keys are forbidden.")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("Non-finite JSON number")

    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
        # Escaped lone surrogates are legal to json.loads but cannot be emitted
        # as UTF-8 packets. Reject them at the wire boundary, not during export.
        pending = [result]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                item.encode("utf-8", errors="strict")
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise WorkspaceError("invalid_json", "Input is not valid bounded JSON.") from None
