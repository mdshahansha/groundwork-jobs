"""JW-21: source posts, opportunity identity, layered deduplication, pagination, reversible merge
(FR-DED-01, FR-DED-03).

Every sighting of a job is a `source_post` and keeps its own provenance. An opportunity groups
posts. Layers 1-3 (provider + external ID, canonical URL, employer + requisition) merge
automatically; layers 4-5 (company + title + location, near-duplicate text) only propose a
merge unless their confidence reaches the auto threshold; layer 6 (recruiter overlap) never
merges by itself. Different requisition IDs or different locations never merge at any layer.
A merge only re-points posts, so `unmerge` returns each post to the opportunity it came from.
"""

import base64
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .contracts import canonical, require, string, utcnow

TRACKING = re.compile(r"^(utm_.*|gclid|fbclid|trk|trackingid|refid|ref|src|source)$", re.I)
AUTO_THRESHOLD = {4: 0.95, 5: 0.95, 6: None}
PROPOSE_TEXT = 0.6
POST_FIELDS = {"provider", "company", "title", "location", "text"}
OPTIONAL = {"external_id", "url", "requisition", "recruiter", "job_id",
            # lead intake (leads.py): kept in the post data for the phase-2 filters
            "posted_at", "min_years", "max_years", "contact_email", "skills"}


def key(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "")).split()).casefold()


def canonical_url(url):
    if not url:
        return None
    parts = urlsplit(url.strip())
    require(parts.scheme in ("http", "https") and parts.hostname, "invalid_schema", "Post URL must be http(s).")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k)))
    host = parts.hostname.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def shingles(text, size=3):
    words = key(text).split()
    return sorted({" ".join(words[i:i + size]) for i in range(max(1, len(words) - size + 1))})


def similarity(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


class Opportunities:
    def __init__(self, workspace):
        self.ws = workspace
        self.db = workspace.db

    def _new(self, now):
        from .workspace import identifier

        opportunity = identifier("opp")
        self.db.execute("INSERT INTO opportunities VALUES (?,?)", (opportunity, now))
        return opportunity

    @staticmethod
    def _compatible(post, other):
        if post["requisition"] and other["requisition"] and post["requisition"] != other["requisition"]:
            return False
        return post["location_key"] == other["location_key"]

    def _match(self, post):
        """Best (layer, confidence, opportunity) among existing posts, or None."""
        best = None
        for other in self.db.execute("SELECT * FROM source_posts").fetchall():
            if not self._compatible(post, other):
                continue
            if post["external_id"] and (post["provider"], post["external_id"]) == (other["provider"], other["external_id"]):
                found = (1, 1.0)
            elif post["canonical_url"] and post["canonical_url"] == other["canonical_url"]:
                found = (2, 1.0)
            elif post["requisition"] and post["company_key"] == other["company_key"] and \
                    post["requisition"] == other["requisition"]:
                found = (3, 1.0)
            elif (post["company_key"], post["title_key"]) == (other["company_key"], other["title_key"]):
                found = (4, 0.9)
            else:
                text = similarity(json.loads(post["shingles"]), json.loads(other["shingles"]))
                if text >= PROPOSE_TEXT and post["company_key"] == other["company_key"]:
                    found = (5, round(text, 3))
                elif post["recruiter"] and post["recruiter"] == other["recruiter"]:
                    found = (6, 0.5)
                else:
                    continue
            candidate = (found[0], -found[1], other["opportunity_id"])
            if best is None or candidate < best:
                best = candidate
        return None if best is None else (best[0], -best[1], best[2])

    def ingest(self, post):
        require(isinstance(post, dict), "invalid_schema", "Post must be an object.")
        require(POST_FIELDS <= set(post) <= POST_FIELDS | OPTIONAL, "invalid_schema",
                "Post needs provider, company, title, location, text.")
        for field in ("provider", "company", "title", "location"):
            string(post[field], 200)
        string(post["text"], 20000)
        if post.get("job_id"):
            self.ws.store.one("jobs", post["job_id"])
        row = {"provider": key(post["provider"]), "external_id": post.get("external_id"),
               "canonical_url": canonical_url(post.get("url")), "company_key": key(post["company"]),
               "title_key": key(post["title"]), "location_key": key(post["location"]),
               "requisition": key(post.get("requisition")) or None, "recruiter": key(post.get("recruiter")) or None,
               "shingles": json.dumps(shingles(post["text"]))}
        from .workspace import identifier

        with self.ws.store.transaction():
            if row["external_id"]:
                existing = self.db.execute("SELECT id, opportunity_id FROM source_posts WHERE provider=? AND "
                                           "external_id=?", (row["provider"], row["external_id"])).fetchone()
                if existing:
                    return {"post_id": existing["id"], "opportunity_id": existing["opportunity_id"],
                            "reused": True, "merge": None}
            now = utcnow()
            match = self._match(row)
            origin = self._new(now)
            post_id = identifier("post")
            merge = None
            target = origin
            if match:
                layer, confidence, existing = match
                threshold = AUTO_THRESHOLD.get(layer, 0)
                auto = layer <= 3 or (threshold is not None and confidence >= threshold)
                merge = {"merge_id": identifier("mrg"), "layer": layer, "confidence": confidence,
                         "state": "merged" if auto else "proposed", "into": existing}
                self.db.execute("INSERT INTO merges VALUES (?,?,?,?,?,?,?,?)",
                                (merge["merge_id"], existing, origin, layer, confidence, merge["state"], now, now))
                if auto:
                    target = existing
            self.db.execute("INSERT INTO source_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (post_id, row["provider"], row["external_id"], row["canonical_url"], row["company_key"],
                             row["title_key"], row["location_key"], row["requisition"], row["recruiter"],
                             row["shingles"], canonical(post), origin, target, post.get("job_id"), now))
            self.ws.store.audit("post_ingested", post_id)
        return {"post_id": post_id, "opportunity_id": target, "reused": False, "merge": merge}

    def decide(self, merge_id, accept):
        require(accept in (True, False), "invalid_schema", "accept must be a boolean.")
        with self.ws.store.transaction():
            merge = self.ws.store.one("merges", merge_id)
            require(merge["state"] == "proposed", "merge_not_proposed", "Only a proposed merge can be decided.")
            state = "merged" if accept else "rejected"
            if accept:
                self.db.execute("UPDATE source_posts SET opportunity_id=? WHERE opportunity_id=?",
                                (merge["into_id"], merge["absorbed_id"]))
            self.db.execute("UPDATE merges SET state=?,updated_at=? WHERE id=?", (state, utcnow(), merge_id))
            self.ws.store.audit("merge_" + state, merge_id)
        return {"merge_id": merge_id, "state": state}

    def unmerge(self, merge_id):
        """Send every post that originated in the absorbed opportunity back to it."""
        with self.ws.store.transaction():
            merge = self.ws.store.one("merges", merge_id)
            require(merge["state"] == "merged", "merge_not_active", "Only an active merge can be undone.")
            moved = self.db.execute("UPDATE source_posts SET opportunity_id=? WHERE origin_opportunity=? AND "
                                    "opportunity_id=?", (merge["absorbed_id"], merge["absorbed_id"],
                                                         merge["into_id"])).rowcount
            self.db.execute("UPDATE merges SET state='undone',updated_at=? WHERE id=?", (utcnow(), merge_id))
            self.ws.store.audit("merge_undone", merge_id)
        return {"merge_id": merge_id, "state": "undone", "posts_restored": moved}

    def opportunity(self, opportunity_id):
        self.ws.store.one("opportunities", opportunity_id)
        posts = self.db.execute("SELECT id, provider, data, job_id FROM source_posts WHERE opportunity_id=? "
                                "ORDER BY created_at, id", (opportunity_id,)).fetchall()
        return {"opportunity_id": opportunity_id,
                "sources": [{"post_id": p["id"], "provider": p["provider"], "job_id": p["job_id"],
                             "url": json.loads(p["data"]).get("url")} for p in posts]}

    def page(self, cursor=None, limit=20):
        """Opportunities that hold at least one post, oldest first, by an opaque keyset cursor:
        stable under concurrent inserts, no offset drift."""
        require(type(limit) is int and 1 <= limit <= 100, "invalid_schema", "limit is 1..100.")
        after = ("", "")
        if cursor is not None:
            try:
                after = tuple(json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()))
                require(len(after) == 2, "invalid_cursor", "Cursor is malformed.")
            except (ValueError, TypeError, UnicodeError, AttributeError):
                require(False, "invalid_cursor", "Cursor is malformed.")
        rows = self.db.execute("SELECT o.id, o.created_at FROM opportunities o WHERE EXISTS (SELECT 1 FROM "
                               "source_posts p WHERE p.opportunity_id=o.id) AND (o.created_at, o.id) > (?, ?) "
                               "ORDER BY o.created_at, o.id LIMIT ?", (*after, limit + 1)).fetchall()
        items = [self.opportunity(r["id"]) for r in rows[:limit]]
        following = None
        if len(rows) > limit:
            last = rows[limit - 1]
            following = base64.urlsafe_b64encode(json.dumps([last["created_at"], last["id"]]).encode()).decode()
        return {"items": items, "next_cursor": following}


def prior_applications(ws, job_id, within_days=None):
    """FR-DED-03: earlier applications to the same employer + requisition, or employer + title
    (within `within_days` when set). Manual outcomes and imported history both count."""
    from datetime import timedelta
    from .contracts import instant

    job = json.loads(ws.store.one("jobs", job_id)["data"])
    company, title, requisition = key(job["company"]), key(job["title"]), key(job.get("requisition"))
    since = None if within_days is None else instant(utcnow()) - timedelta(days=within_days)
    found = []
    for row in ws.db.execute("SELECT o.job_id, o.effective_at, j.data FROM outcomes o JOIN jobs j ON j.id=o.job_id "
                             "WHERE o.kind='manual_applied' AND o.job_id<>?", (job_id,)):
        other = json.loads(row["data"])
        same_req = requisition and key(other.get("requisition")) == requisition
        same_title = key(other["title"]) == title and (since is None or instant(row["effective_at"]) >= since)
        if key(other["company"]) == company and (same_req or same_title):
            found.append({"source": "outcome", "job_id": row["job_id"], "applied_at": row["effective_at"]})
    for row in ws.db.execute("SELECT import_id, line, company, title, applied_on FROM history_rows "
                             "WHERE status='imported'"):
        recent = since is None or instant(row["applied_on"] + "T00:00:00+00:00") >= since
        if key(row["company"]) == company and key(row["title"]) == title and recent:
            found.append({"source": "history", "import_id": row["import_id"], "line": row["line"],
                          "applied_at": row["applied_on"]})
    return found
