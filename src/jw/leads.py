"""Lead intake: turn job sources into JW-21 source posts.

Sources are read-only and legitimate: job-alert and recruiter-invite e-mails already in the
candidate's mailbox (Naukri invites today), LinkedIn hiring posts collected elsewhere (Apify export
or a paced, signed-in browser session) and public job feeds (Himalayas, RemoteOK). Every parser is
pure: it takes what the source returned and gives a post or None, so a format change shows up as
`unparsed`, never as a wrong job. Fetching lives in `fetch_*`; nothing here signs in, scrapes a
page or applies anywhere. Deduplication is the existing `Opportunities.ingest`.
"""

from datetime import datetime, timezone
import base64
import html as htmllib
import re

from .contracts import require
from .opportunities import Opportunities

SOURCES = ("naukri_mail", "linkedin_posts", "himalayas", "remoteok")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
YEARS = re.compile(r"(\d{1,2})\s*(?:\+|(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*(?:years?|yrs?)", re.I)
INDIA = re.compile(r"India|Bangalore|Bengaluru|Pune|Hyderabad|Chennai|Noida|Gurgaon|Gurugram|Mumbai|Kolkata|"
                   r"Delhi|Ahmedabad|Kochi|Jaipur|Indore|Coimbatore|Mohali|Chandigarh|Bhubaneswar|"
                   r"Trivandrum|Thiruvananthapuram|Nagpur|Lucknow|Ghaziabad|Remote", re.I)
ROLE = re.compile(r"((?:(?:Senior|Sr\.?|Junior|Lead|Principal|Associate|Mid[- ]Level|Java|Node(?:\.?js)?|"
                  r"React(?:\.?js)?(?: Native)?|MERN(?: Stack)?|Full[- ]?Stack|Backend|Back[- ]end|Frontend|"
                  r"Front[- ]end|Python|Golang|Go|Mobile|Android|Software|AI|GenAI|ML|TypeScript|JavaScript|"
                  r"Next\.?js|Spring Boot|Web|App|Application|Cross[- ]Platform|Platform)[\s/&+,-]*){1,5}"
                  r"(?:Developers?|Engineers?|Architect|SDE[- ]?(?:I{1,3}|[123])?))", re.I)
FREE_MAIL = ("gmail.com", "yahoo.com", "yahoo.in", "outlook.com", "hotmail.com", "rediffmail.com")


def years(text):
    """(min, max) years the posting asks for, from the first range or N+ it states; (None, None) if none."""
    for match in YEARS.finditer(text or ""):
        low = int(match.group(1))
        if 0 <= low < 30:
            high = int(match.group(2)) if match.group(2) else None
            return low, high
    return None, None


def html_lines(html):
    """Visible text of an e-mail, one block per line. Scripts, styles and comments are dropped."""
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>|<!--.*?-->", " ", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|td|li|h\d|table)>", "\n", text)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def message_html(payload):
    """First text/html part of a Gmail API payload (format=full)."""
    if payload.get("mimeType", "").startswith("text/html") and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        found = message_html(part)
        if found:
            return found
    return ""


def _post(provider, company, title, location, text, **optional):
    post = {"provider": provider, "company": company.strip()[:200], "title": title.strip()[:200],
            "location": (location or "Not stated").strip()[:200], "text": text.strip()[:20000]}
    post.update({k: v for k, v in optional.items() if v not in (None, "", [])})
    return post


def parse_naukri_invite(message):
    """Naukri recruiter invite ("✉️ Job | <title> in <city>"): company, title, location, experience,
    skills and description. Other Naukri mail (digests, badges, confirmations) is not a lead: None."""
    subject = message.get("subject", "")
    head = re.match(r"\W*Job\s*\|\s*(.+?)\s+in\s+(.+?)\s*$", subject)
    if not head:
        return None
    lines = html_lines(message.get("html", ""))
    try:
        start = next(i for i, line in enumerate(lines) if "invited to apply" in line.casefold())
    except StopIteration:
        return None
    block = [line for line in lines[start + 1:] if not re.fullmatch(r"[\d.]+|\(\d+ Reviews\)", line)]
    if len(block) < 3:
        return None
    company, title = block[0], block[1]
    experience = next((line for line in block[2:8] if YEARS.search(line)), "")
    skills = next((line for line in block[2:10] if line.count(",") >= 2), "")
    try:
        jd_at = block.index("Job description")
        stop = next((i for i in range(jd_at + 1, len(block)) if block[i] == "Apply now"), len(block))
        description = "\n".join(block[jd_at + 1:stop])
    except ValueError:
        description = ""
    mid = re.search(r"[?&]mid=(\d+)", message.get("html", ""))
    low, high = years(experience)
    text = "\n".join(filter(None, [f"{title} at {company}, {head.group(2)}", f"Experience: {experience}",
                                   f"Skills: {skills}" if skills else "", description]))
    return _post("naukri", company, title or head.group(1), head.group(2), text,
                 external_id=mid.group(1) if mid else message.get("message_id"),
                 recruiter=message.get("from"), posted_at=message.get("received_at"),
                 min_years=low, max_years=high, skills=skills)


def parse_linkedin_post(item):
    """A LinkedIn hiring post ({text, url?, author?, posted_at?}). Needs a contact e-mail in the text."""
    text = " ".join((item.get("text") or "").split())
    emails = [e.lower().rstrip(".") for e in EMAIL.findall(text)]
    if not emails:
        return None
    role = ROLE.search(text)
    place = INDIA.search(text)
    domain = emails[0].split("@")[1]
    company = item.get("company") or (domain.split(".")[0] if domain not in FREE_MAIL else item.get("author") or domain)
    activity = re.search(r"activity[-:](\d{15,})", item.get("url") or "")
    low, high = years(text)
    return _post("linkedin_post", company, role.group(1) if role else "Software Developer",
                 place.group(0) if place else "Not stated", text,
                 external_id=activity.group(1) if activity else None, url=item.get("url"),
                 recruiter=item.get("author"), posted_at=item.get("posted_at"), contact_email=emails[0],
                 min_years=low, max_years=high)


def parse_himalayas(job):
    places = ", ".join(job.get("locationRestrictions") or []) or "Remote"
    text = re.sub(r"<[^>]+>", " ", job.get("description") or job.get("excerpt") or "")
    low, high = years(text)
    posted = job.get("pubDate")
    if isinstance(posted, (int, float)):
        posted = datetime.fromtimestamp(posted, timezone.utc).isoformat()
    return _post("himalayas", job.get("companyName") or "Unknown", job.get("title") or "Unknown",
                 "Remote (" + places + ")", text or job.get("title", ""), external_id=job.get("guid"),
                 url=job.get("applicationLink"), posted_at=posted, min_years=low, max_years=high,
                 skills=", ".join(job.get("categories") or []))


def parse_remoteok(job):
    if "position" not in job:  # the feed's first element is a legal notice, not a job
        return None
    text = re.sub(r"<[^>]+>", " ", job.get("description") or "")
    low, high = years(text)
    return _post("remoteok", job.get("company") or "Unknown", job["position"],
                 "Remote (" + (job.get("location") or "anywhere") + ")", text or job["position"],
                 external_id=str(job.get("id")), url=job.get("url"), posted_at=job.get("date"),
                 min_years=low, max_years=high, skills=", ".join(job.get("tags") or []))


PARSERS = {"naukri_mail": parse_naukri_invite, "linkedin_posts": parse_linkedin_post,
           "himalayas": parse_himalayas, "remoteok": parse_remoteok}


def _repost(ws, post):
    """Same contact e-mail and same role already ingested: a repost, not a new lead."""
    from .opportunities import key

    if not post.get("contact_email"):
        return None
    row = ws.db.execute("SELECT id, opportunity_id FROM source_posts WHERE title_key=? AND "
                        "json_extract(data, '$.contact_email')=?", (key(post["title"]), post["contact_email"])).fetchone()
    return {"post_id": row["id"], "opportunity_id": row["opportunity_id"]} if row else None


def import_leads(ws, source, items):
    """Parse and ingest one source's raw items. Returns counts plus each new post's opportunity."""
    from .contracts import WorkspaceError

    require(source in PARSERS, "invalid_schema", "source is one of " + ", ".join(SOURCES) + ".")
    require(isinstance(items, list) and len(items) <= 2000, "invalid_schema", "items is a list of at most 2000.")
    opportunities = Opportunities(ws)
    report = {"source": source, "seen": len(items), "unparsed": 0, "new": 0, "reused": 0,
              "merged": 0, "proposed": 0, "rejected": {}, "posts": []}
    for item in items:
        post = PARSERS[source](item) if isinstance(item, dict) else None
        if post is None:
            report["unparsed"] += 1
            continue
        repost = _repost(ws, post)
        if repost:
            report["reused"] += 1
            report["posts"].append(dict(repost, title=post["title"], company=post["company"]))
            continue
        try:
            result = opportunities.ingest(post)
        except WorkspaceError as exc:
            report["rejected"][exc.code] = report["rejected"].get(exc.code, 0) + 1
            continue
        merge = result["merge"]
        if result["reused"]:
            report["reused"] += 1
        elif merge and merge["state"] == "merged":
            report["merged"] += 1
        else:
            report["new"] += 1
            if merge:
                report["proposed"] += 1
        report["posts"].append({"post_id": result["post_id"], "opportunity_id": result["opportunity_id"],
                                "title": post["title"], "company": post["company"]})
    return report


def fetch_naukri_invites(transport, days=7, limit=100):
    """Naukri recruiter invites from the mailbox through a read-only Gmail transport."""
    refs, token = [], None
    query = f'from:naukri.com subject:"Job |" newer_than:{int(days)}d'
    while len(refs) < limit:
        page = transport.list(query, token)
        refs += page.get("messages", [])
        token = page.get("nextPageToken")
        if not token:
            break
    out = []
    for ref in refs[:limit]:
        message = transport.get(ref["id"])
        headers = {h["name"].casefold(): h["value"] for h in message["payload"].get("headers", [])}
        out.append({"message_id": message["id"], "subject": headers.get("subject", ""),
                    "from": headers.get("from", ""), "html": message_html(message["payload"]),
                    "received_at": datetime.fromtimestamp(int(message["internalDate"]) / 1000,
                                                          timezone.utc).isoformat()})
    return out


FEEDS = {"himalayas": "https://himalayas.app/jobs/api?limit=100", "remoteok": "https://remoteok.com/api"}


def fetch_feed(source, timeout=30):
    """Public job feed (no account, no key) as the list its parser expects."""
    import json
    import urllib.request

    require(source in FEEDS, "invalid_schema", "Feed is himalayas or remoteok.")
    request = urllib.request.Request(FEEDS[source], headers={"User-Agent": "jw-lead-intake/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        require(False, "transient", f"{source} feed unavailable ({type(exc).__name__}).")
    return data.get("jobs", []) if isinstance(data, dict) else data
