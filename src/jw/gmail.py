"""JW-02: durable Gmail adapter (FR-SYN-01, FR-EML-03, FR-EML-04, FR-RES-03).

The adapter turns a Gmail transport into MailSync input and Executor outcomes. Transports:
- `DemoGmail`: in-memory mailbox with fault injection (expired history, quota, crash, lost send).
- `ReplayGmail`: replays normalized messages from a local JSON file, e.g. a read-only export.
- `HttpGmail`: the Gmail REST API with a bearer token. It is not exercised by the test suite.

Contracts:
- History sync: the durable cursor is `mail_checkpoint`. Messages are fetched, sorted by history
  ID and committed one per transaction, each advancing the cursor; the page `historyId` is written
  only after the whole batch committed. A crash mid-batch resumes after the last committed message
  and MailSync's message-ID dedupe drops anything replayed.
- Expired history (404) or an empty cursor runs a full rebuild over `messages.list`, then sets the
  cursor to the mailbox `historyId` read before the rebuild, so nothing arriving during it is lost.
- Quota: every call spends Gmail quota units from a per-run budget. A 429 or rate-limit 403, or an
  exhausted budget, pauses the run with progress kept; it never retries in a loop.
- Labels are applied after the message commits. A label failure is counted, never rolled back.
- Send: the attempt is reserved (JW-12) before the provider call and carries `X-JW-Action-Id` in a
  header and in the body. Provider 4xx is failed; timeout, connection loss, 429 and 5xx are
  unknown, never resent, and reconciled from the Sent folder.
"""

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from .contracts import WorkspaceError, require, string, utcnow
from .integrations import gmail_permission
from .mailsync import MailSync

UNITS = {"profile": 1, "history": 2, "list": 5, "get": 5, "labels": 1, "create_label": 5, "modify": 5,
         "send": 100, "search": 5}
DEFAULT_BUDGET = 5000
REBUILD_QUERY = "newer_than:60d"
LABEL = "jw/synced"
MAX_BODY = 100_000


class GmailError(Exception):
    """kind: history_expired | quota | transient | auth | rejected."""

    def __init__(self, kind, message="", retry_after=None):
        super().__init__(message or kind)
        self.kind = kind
        self.retry_after = retry_after


class _Paused(Exception):
    def __init__(self, state, retry_after=None):
        super().__init__(state)
        self.state = state
        self.retry_after = retry_after


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _text(payload):
    """First text/plain part, else text/plain-like body; bounded."""
    if payload.get("mimeType", "text/plain").startswith("text/plain") and payload.get("body", {}).get("data"):
        return _unb64(payload["body"]["data"]).decode("utf-8", "replace")[:MAX_BODY]
    for part in payload.get("parts", []) or []:
        found = _text(part)
        if found:
            return found
    return ""


def _address(value):
    value = value.strip()
    if "<" in value and value.endswith(">"):
        value = value[value.rindex("<") + 1:-1]
    return value.strip()


def normalize(message):
    """Gmail API message (format=full) to the MailSync message shape."""
    payload = message.get("payload", {})
    headers = {h["name"].casefold(): h["value"] for h in payload.get("headers", [])}
    refs = (headers.get("references", "") + " " + headers.get("in-reply-to", "")).split()
    received = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc).isoformat()
    return {"message_id": message["id"], "thread_id": message["threadId"], "history_id": int(message["historyId"]),
            "from": _address(headers.get("from", "unknown@invalid")), "subject": headers.get("subject", "")[:2000],
            "body": _text(payload), "received_at": received,
            "references": [r.strip("<>")[:200] for r in refs][:50]}


def gmail_message(m, labels=("INBOX",)):
    """MailSync message shape to a Gmail API message; used by the demo and replay transports."""
    received = datetime.fromisoformat(m["received_at"].replace("Z", "+00:00"))
    headers = [{"name": "From", "value": m["from"]}, {"name": "Subject", "value": m["subject"]}]
    headers += [{"name": k, "value": v} for k, v in m.get("headers", {}).items()]
    if m.get("references"):
        headers.append({"name": "References", "value": " ".join("<%s>" % r for r in m["references"])})
    return {"id": m["message_id"], "threadId": m["thread_id"], "historyId": str(m["history_id"]),
            "internalDate": str(int(received.timestamp() * 1000)), "labelIds": list(labels),
            "payload": {"mimeType": "text/plain", "headers": headers,
                        "body": {"data": _b64(m["body"].encode("utf-8"))}}}


class DemoGmail:
    """In-memory Gmail. Faults are armed per test: `expire_history`, `quota_after`, `crash_on_get`,
    `send_fault` ('timeout' | 'rejected' | None), `label_fault`."""

    def __init__(self, account="demo@example.invalid", scopes=("gmail.modify",)):
        self.account = account
        self.scopes = set(scopes)
        self.history_id = 1000
        self.messages = {}
        self.events = []  # (history_id, message_id)
        self.labels = {"INBOX": "INBOX", "SENT": "SENT"}
        self.expire_history = False
        self.quota_after = None
        self.crash_on_get = set()
        self.send_fault = None
        self.label_fault = False
        self.calls = []

    def _call(self, name):
        self.calls.append(name)
        if self.quota_after is not None:
            if self.quota_after <= 0:
                raise GmailError("quota", "rateLimitExceeded", retry_after=60)
            self.quota_after -= 1

    def deliver(self, sender, subject, body, thread=None, labels=("INBOX",), headers=None, references=()):
        self.history_id += 1
        mid = "demo%05d" % self.history_id
        m = {"message_id": mid, "thread_id": thread or "thr" + mid, "history_id": self.history_id, "from": sender,
             "subject": subject, "body": body, "received_at": utcnow(), "headers": headers or {},
             "references": list(references)}
        self.messages[mid] = gmail_message(m, labels)
        self.events.append((self.history_id, mid))
        return mid

    def profile(self):
        self._call("profile")
        return {"emailAddress": self.account, "historyId": str(self.history_id)}

    def history(self, start, page_token=None):
        self._call("history")
        if self.expire_history:
            raise GmailError("history_expired", "startHistoryId too old")
        added = [(h, mid) for h, mid in self.events if h > int(start)]
        offset = int(page_token or 0)
        chunk = added[offset:offset + 2]
        page = {"historyId": str(self.history_id),
                "history": [{"id": str(h), "messagesAdded": [{"message": {"id": mid}}]} for h, mid in chunk]}
        if offset + 2 < len(added):
            page["nextPageToken"] = str(offset + 2)
        return page

    def list(self, query, page_token=None):
        self._call("list")
        ids = sorted(mid for mid, m in self.messages.items() if "SENT" not in m["labelIds"])
        offset = int(page_token or 0)
        page = {"messages": [{"id": mid} for mid in ids[offset:offset + 3]]}
        if offset + 3 < len(ids):
            page["nextPageToken"] = str(offset + 3)
        return page

    def get(self, message_id):
        self._call("get")
        if message_id in self.crash_on_get:
            self.crash_on_get.discard(message_id)
            raise GmailError("transient", "connection reset")
        return json.loads(json.dumps(self.messages[message_id]))

    def label_ids(self):
        self._call("labels")
        return dict(self.labels)

    def create_label(self, name):
        self._call("create_label")
        self.labels[name] = "Label_%d" % len(self.labels)
        return self.labels[name]

    def modify(self, message_id, add):
        self._call("modify")
        if self.label_fault:
            raise GmailError("transient", "label write failed")
        self.messages[message_id]["labelIds"] = sorted(set(self.messages[message_id]["labelIds"]) | set(add))

    def send(self, raw):
        self._call("send")
        if self.send_fault == "rejected":
            raise GmailError("rejected", "invalid To header")
        mime = _unb64(raw).decode("utf-8")
        self.sent_raw = getattr(self, "sent_raw", []) + [mime]
        head, _, body = mime.partition("\n\n")
        headers = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
        self.history_id += 1
        mid = "sent%05d" % self.history_id
        m = {"message_id": mid, "thread_id": "thr" + mid, "history_id": self.history_id, "from": self.account,
             "subject": headers.get("Subject", ""), "body": body, "received_at": utcnow(),
             "headers": {"X-JW-Action-Id": headers.get("X-JW-Action-Id", ""), "To": headers.get("To", "")}}
        self.messages[mid] = gmail_message(m, ("SENT",))
        if self.send_fault == "timeout":
            # The provider accepted it; the response was lost.
            raise GmailError("transient", "read timed out")
        return {"id": mid, "threadId": "thr" + mid, "labelIds": ["SENT"]}

    def search_sent(self, text, query=None):
        self._call("search")
        hits = []
        for m in self.messages.values():
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            if "SENT" in m["labelIds"] and (text in _text(m["payload"]) or headers.get("X-JW-Action-Id") == text):
                hits.append({"message_id": m["id"], "thread_id": m["threadId"], "headers": headers})
        return hits


class ReplayGmail(DemoGmail):
    """Replays a JSON list of MailSync-shaped messages as a read-only mailbox. Sending is refused."""

    def __init__(self, path, account="replay@example.invalid"):
        super().__init__(account, scopes=("gmail.readonly",))
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        require(isinstance(records, list), "invalid_schema", "Replay file is a list of messages.")
        for m in sorted(records, key=lambda r: r["history_id"]):
            self.messages[m["message_id"]] = gmail_message(m)
            self.events.append((m["history_id"], m["message_id"]))
            self.history_id = max(self.history_id, m["history_id"])

    def modify(self, message_id, add):
        raise GmailError("auth", "Replay mailbox is read-only.")

    def send(self, raw):
        raise GmailError("auth", "Replay mailbox is read-only.")


class HttpGmail:
    """Gmail REST v1 over urllib. Token from the caller (never stored). Not exercised by tests."""

    BASE = "https://gmail.googleapis.com/gmail/v1/users/me/"

    def __init__(self, access_token, scopes, timeout=30):
        string(access_token, 4096)
        self.token = access_token
        self.scopes = set(scopes)
        self.timeout = timeout

    def _req(self, method, path, query=None, body=None):
        url = self.BASE + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:2000].decode("utf-8", "replace")
            if exc.code == 404 and path == "history":
                raise GmailError("history_expired", detail) from None
            if exc.code == 429 or (exc.code == 403 and "rateLimit" in detail):
                raise GmailError("quota", detail, retry_after=exc.headers.get("Retry-After")) from None
            if exc.code == 401:
                raise GmailError("auth", detail) from None
            if exc.code >= 500 or exc.code == 408:
                raise GmailError("transient", detail) from None
            raise GmailError("rejected", detail) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GmailError("transient", str(exc)) from None

    def profile(self):
        return self._req("GET", "profile")

    def history(self, start, page_token=None):
        query = {"startHistoryId": start, "historyTypes": "messageAdded"}
        if page_token:
            query["pageToken"] = page_token
        return self._req("GET", "history", query)

    def list(self, query, page_token=None):
        params = {"q": query, "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        return self._req("GET", "messages", params)

    def get(self, message_id):
        return self._req("GET", "messages/" + urllib.parse.quote(message_id), {"format": "full"})

    def label_ids(self):
        return {label["name"]: label["id"] for label in self._req("GET", "labels").get("labels", [])}

    def create_label(self, name):
        return self._req("POST", "labels", body={"name": name})["id"]

    def modify(self, message_id, add):
        self._req("POST", "messages/" + urllib.parse.quote(message_id) + "/modify", body={"addLabelIds": list(add)})

    def send(self, raw):
        return self._req("POST", "messages/send", body={"raw": raw})

    def search_sent(self, text, query=None):
        hits = []
        for ref in self.list(query or 'in:sent "%s"' % text).get("messages", []):
            m = self.get(ref["id"])
            hits.append({"message_id": m["id"], "thread_id": m["threadId"],
                         "headers": {h["name"]: h["value"] for h in m["payload"].get("headers", [])}})
        return hits


class GmailAdapter:
    def __init__(self, executor, transport, budget=DEFAULT_BUDGET, label=LABEL, allowed=("read",)):
        require(type(budget) is int and 1 <= budget <= 1_000_000, "invalid_schema", "Budget is 1..1000000 units.")
        self.ex = executor
        self.t = transport
        self.mail = MailSync(executor)
        self.budget = budget
        self.spent = 0
        self.label = label
        self.allowed = tuple(allowed)

    def _spend(self, call):
        cost = UNITS[call]
        if self.spent + cost > self.budget:
            raise _Paused("paused_budget")
        self.spent += cost

    def _do(self, call, *args):
        self._spend(call)
        try:
            return getattr(self.t, {"labels": "label_ids", "search": "search_sent"}.get(call, call))(*args)
        except GmailError as exc:
            if exc.kind == "quota":
                raise _Paused("paused_quota", exc.retry_after) from None
            raise

    def _cursor(self, history_id):
        with self.ex.store.transaction():
            self.mail._advance(int(history_id))

    def _label_id(self):
        known = self._do("labels")
        return known.get(self.label) or self._do("create_label", self.label)

    def sync(self):
        """One bounded run. Returns counts, the mode used and the run state."""
        gmail_permission("read", self.t.scopes, self.allowed)
        report = {"mode": None, "state": "complete", "fetched": 0, "matched": 0, "review": 0, "duplicate": 0,
                  "ignored": 0, "labelled": 0, "label_failed": 0, "units": 0, "retry_after": None}
        try:
            cursor = self.mail.checkpoint()
            ids, head = None, None
            if cursor:
                try:
                    ids, head = self._history(cursor)
                    report["mode"] = "history"
                except GmailError as exc:
                    if exc.kind != "history_expired":
                        raise
            if ids is None:
                report["mode"] = "rebuild"
                head = self._do("profile")["historyId"]
                ids = self._rebuild()
            labelled = []
            fetched = sorted((normalize(self._do("get", mid)) for mid in ids), key=lambda m: m["history_id"])
            for message in fetched:
                mid = message["message_id"]
                result = self.mail.sync([message])
                report["fetched"] += 1
                for key in ("matched", "review", "duplicate", "ignored"):
                    report[key] += result[key]
                if result["matched"]:
                    labelled.append(mid)
            self._cursor(head)
            if "label" in self.allowed and labelled:
                label_id = self._label_id()
                for mid in labelled:
                    try:
                        self._do("modify", mid, [label_id])
                        report["labelled"] += 1
                    except GmailError:
                        report["label_failed"] += 1
        except _Paused as pause:
            report["state"], report["retry_after"] = pause.state, pause.retry_after
        except GmailError as exc:
            report["state"] = "failed_" + exc.kind
        report["units"] = self.spent
        report["checkpoint"] = self.mail.checkpoint()
        self.ex.store.audit("gmail_sync_" + report["state"], report["mode"] or "none")
        return report

    def _history(self, cursor):
        token, seen, ids, head = None, set(), [], None
        while True:
            page = self._do("history", str(cursor), token)
            head = page["historyId"]
            for event in page.get("history", []):
                for added in event.get("messagesAdded", []):
                    mid = added["message"]["id"]
                    if mid not in ids:
                        ids.append(mid)
            token = page.get("nextPageToken")
            if not token:
                return ids, head
            require(token not in seen, "history_loop", "Repeated pagination token.")
            seen.add(token)

    def _rebuild(self):
        token, seen, ids = None, set(), []
        while True:
            page = self._do("list", REBUILD_QUERY, token)
            ids += [m["id"] for m in page.get("messages", []) if m["id"] not in ids]
            token = page.get("nextPageToken")
            if not token:
                return ids
            require(token not in seen, "history_loop", "Repeated pagination token.")
            seen.add(token)

    def send(self, token, auth_id, destination, content, guard=None, attachments=(), mark_body=True):
        """Reserve, send once, record. Never resends: a lost response becomes unknown.

        `attachments` is [(filename, bytes, mime type)], checked against the authorised hashes.
        `mark_body=False` keeps the action ID out of the visible text (recruiter-facing mail); it stays
        in the X-JW-Action-Id header, which `reconcile` matches."""
        gmail_permission("send", self.t.scopes, self.allowed)
        files = [(name, data, mime) for name, data, mime in attachments]
        reserved = self.ex.reserve(token, auth_id, "email", destination, content,
                                   attachments=[data for _, data, _ in files], guard=guard)
        action_id = reserved["action_id"]
        message = EmailMessage()
        message["To"] = destination
        message["Subject"] = content["subject"]
        message["X-JW-Action-Id"] = action_id
        footer = "\n\n--\nX-JW-Action-Id: " + action_id + "\n" if mark_body else "\n"
        message.set_content(content["body"] + footer)
        for name, data, mime in files:
            main, _, sub = mime.partition("/")
            message.add_attachment(data, maintype=main, subtype=sub, filename=name)
        raw = _b64(message.as_bytes(policy=message.policy.clone(linesep="\n")))
        try:
            self._spend("send")
            sent = self.t.send(raw)
        except _Paused:
            return self.ex.record(token, action_id, "failed", evidence="Local quota budget refused the call.")
        except GmailError as exc:
            if exc.kind in ("rejected", "auth"):
                return self.ex.record(token, action_id, "failed", evidence=exc.kind + ": " + str(exc)[:500])
            return self.ex.record(token, action_id, "unknown")
        return self.ex.record(token, action_id, "accepted", provider_ref=sent["threadId"])

    def reconcile(self, token, action_id, query=None):
        """`query` narrows the Sent search (e.g. recipient and subject) when the ID is header-only."""
        string(action_id, 100)
        try:
            hits = self._do("search", action_id, query) if query else self._do("search", action_id)
        except (GmailError, _Paused):
            return {"action_id": action_id, "state": "send_unknown",
                    "detail": "Sent-folder search failed; the action stays unknown and is not resent."}
        return self.mail.reconcile_sent(token, action_id, hits)


def transport(spec):
    """CLI transport from {'transport': 'replay', 'path': ...} or {'transport': 'http', 'token_env': ...}."""
    import os

    kind = spec.get("transport")
    if kind == "replay":
        return ReplayGmail(spec["path"])
    if kind == "http":
        name = spec.get("token_env", "GMAIL_ACCESS_TOKEN")
        value = os.environ.get(name)
        require(bool(value), "not_configured", name + " is not set; no Gmail call was made.")
        return HttpGmail(value, spec.get("scopes", ["gmail.readonly"]))
    raise WorkspaceError("invalid_schema", "transport is replay or http.")
