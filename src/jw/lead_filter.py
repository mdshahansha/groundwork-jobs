"""Lead pipeline phase 2: the candidate's lead rules and a fit score over ingested source posts.

Rules (each failure is a reason code, never a silent drop):
  age            posted at most `max_age_hours` ago (default 48); unknown age fails
  experience     the posting's minimum years at most `max_min_years` (default 4); unstated passes
  role           title or text names a target role; excluded stacks and intern/fresher posts fail
  location       India, or remote open to India
  poster         the poster published at most `max_poster_posts` posts in 30 days (default 4).
                 Counted from posts this workspace has seen, so it is a lower bound; a profile
                 check is still needed before sending (reported as `poster_unverified`)
  applied        contact e-mail, or company domain for non-free mail, not already applied to
Survivors get a fit score 0-100 from skill overlap, role match and experience fit, with the
matched skills listed so the score can be checked.
"""

from datetime import datetime, timedelta, timezone
import json
import re

from .contracts import require
from .leads import FREE_MAIL, INDIA

TARGET = re.compile(r"node|react|java\b|spring|full[ -]?stack|mern|backend|back[- ]end|android|gen ?ai|\bai\b|"
                    r"llm|golang|\bgo\b developer|python|typescript|software (?:engineer|developer)|\bsde\b|"
                    r"forward deployed|next\.?js|javascript", re.I)
EXCLUDE = re.compile(r"(?:\.net\b|\bc#|\b(?:intern|internship|unpaid|freshers?|php|laravel|angular developer|SAP|"
                     r"salesforce|QA|tester|devops engineer|data engineer|embedded|business analyst|flutter|project manager|"
                     r"security engineer|female candidates|women candidates|women only|"
                     r"open to work|opentowork)\b)", re.I)
ABROAD = re.compile(r"\b(USA?|Unite[ds]? States|usajobs|OPT|CPT|Texas|California|New York|Virginia|New Jersey|"
                    r"Florida|Illinois|Washington DC|Irving|Dallas|Austin|Seattle|W2|C2C|H1B|H-1B|Green Card|EAD|USC|Canada|UK|United Kingdom|Europe|"
                    r"EU only|Germany|Dubai|UAE|Saudi|Qatar|Singapore|Malaysia|Pakistan|Karachi|Lahore|"
                    r"Philippines|Nigeria|Australia|LATAM|Latin America|Brazil|Mexico)\b")
SKILLS = ("javascript", "typescript", "react", "next.js", "node", "express", "java", "spring boot", "react native",
          "rest", "microservices", "sql", "mysql", "postgresql", "mongodb", "redis", "hibernate", "jpa",
          "spring security", "aws", "docker", "github actions", "ci/cd", "jest", "junit", "mockito", "jwt",
          "oauth", "rbac", "redux", "python", "django", "socket.io", "kafka", "llm")
POLICY = {"max_age_hours": 48, "max_min_years": 4, "max_poster_posts": 4, "skills": list(SKILLS)}


def _when(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _skill(text, skill):
    return re.search(r"(?<![\w.])" + re.escape(skill).replace(r"\ ", r"[\s-]?") + r"(?:\.?js)?(?![\w])", text, re.I)


def fit(post, skills):
    text = " ".join([post["title"], post.get("skills", ""), post["text"]])
    matched = [s for s in skills if _skill(text, s)]
    asked = [s for s in SKILLS if _skill(text, s)]
    overlap = len(matched) / max(len(asked), 1)
    role = 1.0 if TARGET.search(post["title"]) else 0.5
    low = post.get("min_years")
    exp = 1.0 if low is None or low <= 3 else 0.6
    return round(100 * (0.6 * overlap + 0.2 * role + 0.2 * exp)), matched


def screen(ws, policy=None, applied=(), now=None):
    """Every ingested post, grouped by opportunity, checked against the rules. Returns kept leads
    ranked by fit, and drop counts by reason."""
    policy = dict(POLICY, **(policy or {}))
    require(all(type(policy[k]) is int and policy[k] > 0 for k in ("max_age_hours", "max_min_years",
                                                                    "max_poster_posts")),
            "invalid_schema", "Policy limits are positive integers.")
    now = now or datetime.now(timezone.utc)
    applied = {a.strip().lower() for a in applied if a and a.strip()}
    rows = ws.db.execute("SELECT id, opportunity_id, provider, recruiter, data FROM source_posts "
                         "ORDER BY created_at, id").fetchall()
    month = now - timedelta(days=30)
    volume = {}
    for row in rows:
        when = _when(json.loads(row["data"]).get("posted_at"))
        if row["recruiter"] and (when is None or when >= month):
            volume[row["recruiter"]] = volume.get(row["recruiter"], 0) + 1
    kept, dropped, seen = [], {}, set()
    for row in rows:
        if row["opportunity_id"] in seen:
            continue
        seen.add(row["opportunity_id"])
        post = json.loads(row["data"])
        reasons = []
        when = _when(post.get("posted_at"))
        if when is None:
            reasons.append("age_unknown")
        elif now - when > timedelta(hours=policy["max_age_hours"]):
            reasons.append("too_old")
        if post.get("min_years") is not None and post["min_years"] > policy["max_min_years"]:
            reasons.append("experience")
        body = post["title"] + " " + post["text"]
        # A LinkedIn post's title is a guess with a generic fallback, so its role is judged on the text;
        # a feed's title is authoritative and its text mentions unrelated stacks.
        if not TARGET.search(post["text"] if row["provider"] == "linkedin_post" else post["title"]):
            reasons.append("role")
        if EXCLUDE.search(body):
            reasons.append("excluded_stack")
        place = post["location"]
        remote_elsewhere = place.startswith("Remote (") and not re.search(r"India|anywhere|worldwide|global|asia",
                                                                          place, re.I)
        if remote_elsewhere or ABROAD.search(place + " " + body) or not INDIA.search(place + " " + body):
            reasons.append("location")
        if row["recruiter"] and volume.get(row["recruiter"], 0) > policy["max_poster_posts"]:
            reasons.append("poster_volume")
        email = (post.get("contact_email") or "").lower()
        domain = email.split("@")[1] if "@" in email else ""
        if email in applied or (domain and domain not in FREE_MAIL and "@" + domain in applied):
            reasons.append("applied")
        if reasons:
            for reason in reasons:
                dropped[reason] = dropped.get(reason, 0) + 1
            continue
        score, matched = fit(post, policy["skills"])
        kept.append({"post_id": row["id"], "opportunity_id": row["opportunity_id"], "provider": row["provider"],
                     "fit": score, "matched_skills": matched, "title": post["title"], "company": post["company"],
                     "location": post["location"], "posted_at": post.get("posted_at"),
                     "min_years": post.get("min_years"), "contact_email": post.get("contact_email"),
                     "url": post.get("url"), "poster_posts_seen_30d": volume.get(row["recruiter"], 0),
                     "checks_pending": ["poster_unverified"] if row["provider"] == "linkedin_post" else []})
    kept.sort(key=lambda lead: (-lead["fit"], lead["posted_at"] or ""))
    return {"policy": {k: policy[k] for k in ("max_age_hours", "max_min_years", "max_poster_posts")},
            "opportunities": len(seen), "kept": len(kept), "dropped": dropped, "leads": kept}


def applied_from_tracker(path):
    """Contact e-mails and company domains already applied to, from job_search_tracker.csv."""
    import csv

    out = set()
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            email = (row.get("contact_person") or "").strip().lower()
            if "@" in email:
                out.add(email)
                domain = email.split("@")[1]
                if domain not in FREE_MAIL:
                    out.add("@" + domain)
    return out
