"""Lead pipeline phase 4: approve a batch of ready drafts, send each once, reconcile what is unknown.

`approve` is the candidate's batch decision: each ready draft becomes a frozen e-mail envelope (subject,
body, resume hash) with a time-limited authorisation. `send` spends authorisations through the Gmail
adapter: the attempt is reserved before the provider call, the action ID travels in a header only
(recruiters never see it), the resume bytes must match the authorised hash, and a lost response
becomes `unknown` and is never resent. `reconcile` settles unknowns from the Sent folder by recipient
and subject. Bounces and replies arrive through `mail-sync` like any other mail. Suppressed addresses
are refused at approval (JW-04).
"""

from pathlib import Path
import time

from .actions import Actions, content_hash
from .contracts import WorkspaceError, require, utcnow
from .execution import Executor

HOLDER = "lead-queue"


def _resume(path):
    data = Path(path).read_bytes()
    require(data.startswith(b"%PDF") and len(data) <= 5 * 1024 * 1024, "invalid_schema",
            "The resume must be a PDF of at most 5 MB.")
    return Path(path).name, data


def _content(row):
    return {"subject": row["subject"], "body": row["body"]}


def _envelope_for(ws, draft_id):
    """The draft's envelope, found by its frozen content hash and recipient (envelopes hold only subject/body)."""
    row = ws.db.execute("SELECT * FROM lead_drafts WHERE id=?", (draft_id,)).fetchone()
    return ws.db.execute("SELECT e.id AS envelope_id, a.id AS auth_id, a.state AS auth_state, a.expires_at "
                         "FROM action_envelopes e JOIN authorisations a ON a.envelope_id=e.id "
                         "WHERE e.channel='email' AND e.content_hash=? AND e.destination=? "
                         "ORDER BY a.created_at DESC", (content_hash("email", _content(row)),
                                                        row["to_address"])).fetchone()


def approve(ws, draft_ids, resume_path, hours=24):
    """Freeze and authorise ready drafts. A draft that is not ready, or already approved, is skipped."""
    require(isinstance(draft_ids, list) and 1 <= len(draft_ids) <= 200, "invalid_schema",
            "draft_ids is a list of 1..200 drafts.")
    _, resume = _resume(resume_path)
    actions = Actions(ws)
    if actions.mode("email") == "draft_only":
        actions.set_mode("email", "approve_each_action")
    out = {"approved": [], "skipped": {}}
    for draft_id in draft_ids:
        row = ws.db.execute("SELECT * FROM lead_drafts WHERE id=?", (draft_id,)).fetchone()
        reason = None
        if row is None:
            reason = "unknown_draft"
        elif row["state"] != "ready":
            reason = "not_ready"
        elif _envelope_for(ws, draft_id):
            reason = "already_approved"
        if reason is None:
            content = _content(row)
            try:
                envelope = actions.create_envelope("email", row["to_address"], content, attachments=[resume])
                auth = actions.approve(envelope["envelope_id"], hours=hours)
            except WorkspaceError as exc:
                reason = exc.code
            else:
                out["approved"].append({"draft_id": draft_id, "to": row["to_address"],
                                        "authorisation_id": auth["authorisation_id"]})
        if reason:
            out["skipped"][draft_id] = reason
    return out


def send(ws, transport, resume_path, limit=20, pause=4.0, sleep=time.sleep):
    """Send approved, unsent lead drafts once each, paced. Returns per-draft outcomes."""
    from .gmail import GmailAdapter

    require(type(limit) is int and 1 <= limit <= 100, "invalid_schema", "limit is 1..100.")
    name, resume = _resume(resume_path)
    ex = Executor(Actions(ws))
    token = ex.acquire(HOLDER, seconds=3600)["token"]
    adapter = GmailAdapter(ex, transport, allowed=("read", "send"))
    rows = ws.db.execute("SELECT * FROM lead_drafts WHERE state='ready' ORDER BY created_at, id").fetchall()
    results = []
    for row in rows:
        if len(results) >= limit:
            break
        link = _envelope_for(ws, row["id"])
        if not link or link["auth_state"] != "active":
            continue
        if results:
            sleep(pause)
        content = _content(row)
        try:
            sent = adapter.send(token, link["auth_id"], row["to_address"], content,
                                attachments=[(name, resume, "application/pdf")], mark_body=False)
        except WorkspaceError as exc:
            results.append({"draft_id": row["id"], "to": row["to_address"], "state": "refused", "reason": exc.code})
            continue
        if sent["state"] == "sent_accepted":
            with ws.store.transaction():
                ws.db.execute("UPDATE lead_drafts SET state='sent', updated_at=? WHERE id=?", (utcnow(), row["id"]))
        results.append({"draft_id": row["id"], "to": row["to_address"], "state": sent["state"],
                        "action_id": sent["action_id"]})
    return {"sent": sum(r["state"] == "sent_accepted" for r in results), "results": results}


def reconcile(ws, transport):
    """Settle unknown lead sends from the Sent folder. Found: the draft is marked sent. Never resends."""
    from .gmail import GmailAdapter

    ex = Executor(Actions(ws))
    token = ex.acquire(HOLDER, seconds=3600)["token"]
    adapter = GmailAdapter(ex, transport, allowed=("read", "send"))
    unknown = []
    for draft in ws.db.execute("SELECT * FROM lead_drafts WHERE state='ready'").fetchall():
        link = _envelope_for(ws, draft["id"])
        attempt = link and ws.db.execute("SELECT id FROM attempts WHERE authorisation_id=? AND state='unknown'",
                                         (link["auth_id"],)).fetchone()
        if attempt:
            unknown.append({"action_id": attempt["id"], "draft_id": draft["id"], "to_address": draft["to_address"],
                            "subject": draft["subject"]})
    out = []
    for row in unknown:
        query = 'in:sent to:%s subject:"%s"' % (row["to_address"], row["subject"].replace('"', ""))
        settled = adapter.reconcile(token, row["action_id"], query)
        if settled["state"] == "sent_accepted":
            with ws.store.transaction():
                ws.db.execute("UPDATE lead_drafts SET state='sent', updated_at=? WHERE id=?",
                              (utcnow(), row["draft_id"]))
        out.append({"draft_id": row["draft_id"], "action_id": row["action_id"], "state": settled["state"]})
    return {"reconciled": out}

