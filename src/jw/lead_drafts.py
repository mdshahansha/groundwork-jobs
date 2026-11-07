"""Lead pipeline phase 3: one application e-mail per lead, written by the host model, checked here.

`packet` gives the model the post, the candidate facts and the writing standard. `submit` stores the
draft with a risk report and blocks it when a check fails:
  unsupported_numbers   a figure in the e-mail that is in neither the facts nor the post
  unsupported_skills    a technology named in the e-mail but absent from the facts
  banned_phrases        desperate, flattering or stock AI wording
  compensation          CTC, salary or notice period mentioned although the post did not ask
  length                over 180 words, or a subject over 90 characters
  subject               the subject lacks the candidate's name or the role
  resume                the e-mail does not say the resume is attached
  no_contact            the lead has no e-mail address (apply through its URL instead)
Warnings that do not block: `post_asks_personal_data` (date of birth, PAN, Aadhaar...), which the
candidate answers personally. The facts file stays outside the repository; only its path is passed.
"""

import json
import re

from .contracts import canonical, require, string, utcnow
from .lead_filter import SKILLS, _skill

BANNED = ("one chance", "please consider", "desperate", "dream job", "passionate", "rockstar", "ninja", "synergy",
          "leverage", "cutting-edge", "cutting edge", "thrilled", "excited to", "delve", "tapestry",
          "results-driven", "go-getter", "hard-working", "hardworking", "team player", "esteemed", "prestigious",
          "world-class", "i am confident that i", "perfect fit", "look no further", "game-changer")
COMPENSATION = re.compile(r"\b(ctc|lpa|salary|compensation|notice period|serving notice|immediate join\w*)\b", re.I)
PERSONAL = re.compile(r"\b(dob|date of birth|pan card|pan number|aadhaar|aadhar|passport number)\b", re.I)
NUMBER = re.compile(r"\d[\d,.]*\s*(?:%|\+|ms|k\b|lpa)?", re.I)
STANDARD = ("Subject: role + candidate name, plain. Open: address the recruiter, name the role, say why you are "
            "writing. Then about 3 years of full stack work and the 2-3 strengths that match this post, only from "
            "the facts. Close: resume attached, open to a conversation. Under 180 words, short paragraphs. Never "
            "invent or stretch a fact, never name a technology the facts lack, no flattery, no desperation, no "
            "stock AI phrases. No CTC, salary or notice period unless the post asks for them.")


def _post(ws, post_id):
    row = ws.db.execute("SELECT data FROM source_posts WHERE id=?", (post_id,)).fetchone()
    require(row is not None, "not_found", "Unknown lead post.")
    return json.loads(row["data"])


def _facts(path):
    with open(path, encoding="utf-8") as stream:
        return stream.read(200_000)


def packet(ws, post_id, facts_path):
    post = _post(ws, post_id)
    return {"post_id": post_id, "role": post["title"], "company": post["company"], "location": post["location"],
            "to": post.get("contact_email"), "post_text": post["text"], "facts": _facts(facts_path),
            "standard": STANDARD, "response": {"subject": "string", "body": "plain text"}}


def check(post, subject, body, facts, candidate):
    """Risk report for one draft. Pure, so the rules are testable without a workspace."""
    text = subject + "\n" + body
    lower = text.lower()
    source = (facts + "\n" + post["text"] + "\n" + post["title"]).lower()
    numbers = sorted({n.strip().rstrip(".,") for n in NUMBER.findall(text)
                      if n.strip().rstrip(".,") and n.strip().rstrip(".,").lower() not in source})
    skills = sorted(s for s in SKILLS if _skill(text, s) and not _skill(facts, s))
    banned = sorted(p for p in BANNED if p in lower)
    asked_pay = bool(COMPENSATION.search(post["text"]))
    words = len(body.split())
    role_words = [w for w in re.findall(r"[a-z]+", post["title"].lower()) if len(w) > 2]
    blocking = {
        "unsupported_numbers": numbers,
        "unsupported_skills": skills,
        "banned_phrases": banned,
        "compensation": bool(COMPENSATION.search(text)) and not asked_pay,
        "length": words > 180 or len(subject) > 90,
        "subject": candidate.lower() not in subject.lower() or not any(w in subject.lower() for w in role_words),
        "resume": not re.search(r"resume|cv\b|curriculum vitae", body, re.I) or "attach" not in body.lower(),
        "no_contact": not post.get("contact_email"),
    }
    failed = sorted(k for k, v in blocking.items() if v)
    return {"failed": failed, "details": {k: v for k, v in blocking.items() if v and not isinstance(v, bool)},
            "words": words, "post_asks_personal_data": sorted(set(m.lower() for m in PERSONAL.findall(post["text"]))),
            "post_asks_compensation": asked_pay}


def submit(ws, post_id, subject, body, facts_path, candidate):
    from .workspace import identifier

    string(subject, 200)
    string(body, 6000)
    string(candidate, 120)
    post = _post(ws, post_id)
    risk = check(post, subject.strip(), body.strip(), _facts(facts_path), candidate)
    state = "blocked" if risk["failed"] else "ready"
    draft_id = identifier("ldr")
    now = utcnow()
    with ws.store.transaction():
        ws.db.execute("UPDATE lead_drafts SET state='discarded', updated_at=? WHERE post_id=? AND state IN "
                      "('ready','blocked')", (now, post_id))
        ws.db.execute("INSERT INTO lead_drafts VALUES (?,?,?,?,?,?,?,?,?)",
                      (draft_id, post_id, post.get("contact_email") or "", subject.strip(), body.strip(),
                       canonical(risk), state, now, now))
        ws.store.audit("lead_draft_" + state, draft_id)
    return {"draft_id": draft_id, "post_id": post_id, "state": state, "risk": risk}


def drafts(ws, state=None):
    require(state in (None, "ready", "blocked", "sent", "discarded"), "invalid_schema", "Unknown draft state.")
    query = "SELECT * FROM lead_drafts" + (" WHERE state=?" if state else "") + " ORDER BY created_at, id"
    return [dict(row, risk=json.loads(row["risk"])) for row in ws.db.execute(query, (state,) if state else ())]
