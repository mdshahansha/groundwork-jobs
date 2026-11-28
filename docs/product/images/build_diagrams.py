#!/usr/bin/env python3
"""Build the step images for docs/product/STRATEGY_REPORT.md from one set of design tokens.

Run from the repository root:

    python3 docs/product/images/build_diagrams.py

It rewrites the SVG files beside this script. Standard library only. The tokens and
components are documented in README.md in this folder; change them here, not in the SVGs.
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent

# --- Design tokens -------------------------------------------------------------------------

COLOR = {
    "ink": "#0F172A",      # titles
    "text": "#1E293B",     # body text
    "muted": "#64748B",    # captions, file references
    "line": "#94A3B8",     # arrows, connectors
    "border": "#E2E8F0",   # card and panel borders
    "surface": "#FFFFFF",  # canvas
    "panel": "#F8FAFC",    # panel fill
    "track": "#E2E8F0",    # bar track
    "brand": "#3538CD",    # step badge
}
# Node kinds: (accent, tint, label). The label is always printed, so colour is never the only cue.
KIND = {
    "now": ("#475569", "#F1F5F9", "NOW"),
    "gap": ("#B42318", "#FEF3F2", "GAP"),
    "reuse": ("#175CD3", "#EFF8FF", "REUSE"),
    "new": ("#067647", "#ECFDF3", "NEW"),
    "rule": ("#B54708", "#FFFAEB", "RULE"),
    "never": ("#B42318", "#FEF3F2", "NEVER"),
}
# Stage states: (text, fill, border, label).
STATE = {
    "partial": ("#B54708", "#FFFAEB", "#FEDF89", "PARTIAL"),
    "missing": ("#B42318", "#FEF3F2", "#FECDCA", "MISSING"),
    "disconnected": ("#175CD3", "#EFF8FF", "#B2DDFF", "BUILT, NOT WIRED"),
}
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
SIZE = {"title": 24, "subtitle": 14, "panel": 12, "node": 14, "body": 12.5, "ref": 11, "chip": 10.5}
LEADING = {"node": 19, "body": 17, "ref": 15}
RADIUS = {"canvas": 16, "panel": 14, "node": 10, "chip": 6}
SPACE = 8   # base grid; every gap below is a multiple
W = 1200    # canvas width
M = 4 * SPACE  # outer margin

# Average glyph width as a share of font size, used to wrap text (SVG has no wrapping).
GLYPH = {"sans": 0.5, "bold": 0.56, "mono": 0.61}


def wrap(text, size, width, face="sans"):
    limit = max(8, int(width / (size * GLYPH[face])))
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if len(trial) <= limit or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def text(x, y, value, size, color, weight=400, face=FONT, anchor="start", spacing=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{face}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{extra}>{escape(value)}</text>')


def chip(x, y, label, color, fill, border=None, size=SIZE["chip"], anchor="start"):
    """Uppercase pill. Returns (svg, width). With anchor="end", x is the right edge."""
    width = len(label) * size * 0.68 + 2 * SPACE + 2
    left = x - width if anchor == "end" else x
    stroke = f' stroke="{border}"' if border else ""
    svg = (f'<rect x="{left:.1f}" y="{y:.1f}" width="{width:.1f}" height="{size + 9:.1f}" '
           f'rx="{RADIUS["chip"]}" fill="{fill}"{stroke}/>'
           + text(left + width / 2, y + size + 2.5, label, size, color, 700, anchor="middle", spacing="0.6"))
    return svg, width


# --- Components ----------------------------------------------------------------------------

def node_height(node, width):
    inner = width - 3 * SPACE - 6
    _, tag_w = chip(0, 0, KIND[node["kind"]][2], "#000", "#fff")
    h = 2 * SPACE
    h += LEADING["node"] * len(wrap(node["title"], SIZE["node"], inner - tag_w - SPACE, "bold"))
    for item in node.get("body", []):
        h += LEADING["body"] * len(wrap(item, SIZE["body"], inner))
    if node.get("bars"):
        h += SPACE + 22 * len(node["bars"])
    if node.get("ref"):
        h += 4 + LEADING["ref"] * len(wrap(node["ref"], SIZE["ref"], inner, "mono"))
    return h + SPACE + 4


def node_svg(node, x, y, width):
    accent, tint, label = KIND[node["kind"]]
    height = node_height(node, width)
    inner = width - 3 * SPACE - 6
    tx = x + 2 * SPACE + 2
    out = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{RADIUS["node"]}" '
           f'fill="{tint}" stroke="{accent}" stroke-opacity="0.35"/>',
           f'<rect x="{x}" y="{y}" width="6" height="{height}" rx="3" fill="{accent}"/>']
    tag, tag_w = chip(x + width - SPACE - 4, y + SPACE + 2, label, COLOR["surface"], accent, anchor="end")
    out.append(tag)
    cy = y + 2 * SPACE + 6
    for line in wrap(node["title"], SIZE["node"], inner - tag_w - SPACE, "bold"):
        out.append(text(tx, cy, line, SIZE["node"], COLOR["ink"], 700))
        cy += LEADING["node"]
    cy -= 2
    for item in node.get("body", []):
        for line in wrap(item, SIZE["body"], inner):
            out.append(text(tx, cy, line, SIZE["body"], COLOR["text"]))
            cy += LEADING["body"]
    if node.get("bars"):
        cy += SPACE - 4
        top = node.get("max") or max(v for _, v in node["bars"]) or 1
        label_w = 176
        track_x, track_w = tx + label_w, inner - label_w - 40
        for name, value in node["bars"]:
            out.append(text(tx, cy + 4, name, SIZE["body"], COLOR["text"]))
            out.append(f'<rect x="{track_x:.1f}" y="{cy - 7:.1f}" width="{track_w:.1f}" height="12" rx="6" '
                       f'fill="{COLOR["track"]}"/>')
            fill_w = max(3, track_w * value / top) if value else 0
            if fill_w:
                out.append(f'<rect x="{track_x:.1f}" y="{cy - 7:.1f}" width="{fill_w:.1f}" height="12" rx="6" '
                           f'fill="{accent}"/>')
            out.append(text(track_x + track_w + 34, cy + 4, node.get("fmt", "{:g}").format(value),
                            SIZE["body"], COLOR["ink"], 700, anchor="end"))
            cy += 22
        cy -= 4
    if node.get("ref"):
        cy += 4
        for line in wrap(node["ref"], SIZE["ref"], inner, "mono"):
            out.append(text(tx, cy, line, SIZE["ref"], COLOR["muted"], face=MONO))
            cy += LEADING["ref"]
    return "\n".join(out), height


def arrow(cx, y1, y2):
    return (f'<line x1="{cx}" y1="{y1}" x2="{cx}" y2="{y2 - 6}" stroke="{COLOR["line"]}" stroke-width="2"/>'
            f'<path d="M{cx - 6},{y2 - 8} L{cx},{y2} L{cx + 6},{y2 - 8} Z" fill="{COLOR["line"]}"/>')


def panel_height(nodes, width):
    return 6 * SPACE + sum(node_height(n, width - 4 * SPACE) for n in nodes) + 3 * SPACE * (len(nodes) - 1) + 2 * SPACE


def panel_svg(title, kind, nodes, x, y, width, height):
    accent, tint, _ = KIND[kind]
    out = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{RADIUS["panel"]}" '
           f'fill="{COLOR["panel"]}" stroke="{COLOR["border"]}"/>']
    head, _ = chip(x + 2 * SPACE, y + 2 * SPACE, title, accent, tint, accent, size=SIZE["panel"])
    out.append(head)
    cy = y + 6 * SPACE
    inner_w = width - 4 * SPACE
    for i, node in enumerate(nodes):
        svg, h = node_svg(node, x + 2 * SPACE, cy, inner_w)
        out.append(svg)
        cy += h
        if i < len(nodes) - 1:
            out.append(arrow(x + width / 2, cy + 2, cy + 3 * SPACE - 2))
            cy += 3 * SPACE
    return "\n".join(out)


def legend(x, y):
    out, cx = [], x
    out.append(text(cx, y + 13, "Key:", SIZE["ref"], COLOR["muted"], 700))
    cx += 34
    meaning = {"now": "current code", "gap": "defect or missing", "reuse": "exists, reuse it",
               "new": "to build", "rule": "policy or decision", "never": "forbidden"}
    for kind, words in meaning.items():
        accent, _, label = KIND[kind]
        svg, w = chip(cx, y, label, COLOR["surface"], accent)
        out.append(svg)
        cx += w + 6
        out.append(text(cx, y + 13, words, SIZE["ref"], COLOR["muted"]))
        cx += len(words) * SIZE["ref"] * 0.48 + 3 * SPACE
    return "\n".join(out)


def canvas(height, title, desc, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
            f'viewBox="0 0 {W} {height}" role="img" aria-labelledby="title desc">\n'
            f'<title id="title">{escape(title)}</title>\n<desc id="desc">{escape(desc)}</desc>\n'
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1}" rx="{RADIUS["canvas"]}" '
            f'fill="{COLOR["surface"]}" stroke="{COLOR["border"]}"/>\n{body}\n</svg>\n')


def header(number, title, vision, state):
    out = [f'<circle cx="{M + 22}" cy="{M + 22}" r="22" fill="{COLOR["brand"]}"/>',
           text(M + 22, M + 29, str(number), 20, COLOR["surface"], 700, anchor="middle"),
           text(M + 60, M + 20, f"Step {number}: {title}", SIZE["title"], COLOR["ink"], 700)]
    s_color, s_fill, s_border, s_label = STATE[state]
    svg, _ = chip(W - M, M + 2, s_label, s_color, s_fill, s_border, size=12, anchor="end")
    out.append(svg)
    y = M + 44
    for line in wrap("Vision: " + vision, SIZE["subtitle"], W - 2 * M - 60):
        out.append(text(M + 60, y, line, SIZE["subtitle"], COLOR["muted"]))
        y += 20
    return "\n".join(out), y + SPACE


def footer(y, metric, recs):
    width = W - 2 * M
    inner = width - 4 * SPACE - 170
    m_lines = wrap(metric, SIZE["body"], inner)
    r_lines = wrap(recs, SIZE["body"], inner)
    height = 3 * SPACE + LEADING["body"] * (len(m_lines) + len(r_lines)) + SPACE
    out = [f'<rect x="{M}" y="{y}" width="{width}" height="{height}" rx="{RADIUS["node"]}" '
           f'fill="{COLOR["panel"]}" stroke="{COLOR["border"]}"/>']
    cy = y + 2 * SPACE + 6
    out.append(text(M + 2 * SPACE, cy, "SUCCESS METRIC", SIZE["ref"], COLOR["muted"], 700, spacing="0.8"))
    for line in m_lines:
        out.append(text(M + 2 * SPACE + 170, cy, line, SIZE["body"], COLOR["ink"], 600))
        cy += LEADING["body"]
    cy += SPACE
    out.append(text(M + 2 * SPACE, cy, "RECOMMENDATIONS", SIZE["ref"], COLOR["muted"], 700, spacing="0.8"))
    for line in r_lines:
        out.append(text(M + 2 * SPACE + 170, cy, line, SIZE["body"], COLOR["text"]))
        cy += LEADING["body"]
    out.append(legend(M, y + height + 2 * SPACE))
    return "\n".join(out), y + height + 2 * SPACE + 20


def step_image(step):
    head, y = header(step["number"], step["title"], step["vision"], step["state"])
    col_w = (W - 2 * M - 3 * SPACE) // 2
    height = max(panel_height(step["now"], col_w), panel_height(step["target"], col_w))
    left = panel_svg("NOW: WHAT THE CODE DOES", "gap", step["now"], M, y, col_w, height)
    right = panel_svg("TARGET: WHAT TO BUILD", "new", step["target"], M + col_w + 3 * SPACE, y, col_w, height)
    mid_x = M + col_w + 1.5 * SPACE
    bridge = (f'<circle cx="{mid_x}" cy="{y + 3 * SPACE + 2}" r="11" fill="{COLOR["surface"]}" '
              f'stroke="{COLOR["line"]}" stroke-width="1.5"/>'
              f'<path d="M{mid_x - 4},{y + 3 * SPACE - 3} L{mid_x + 3},{y + 3 * SPACE + 2} '
              f'L{mid_x - 4},{y + 3 * SPACE + 7}" fill="none" stroke="{COLOR["line"]}" stroke-width="2"/>')
    foot, end = footer(y + height + 2 * SPACE, step["metric"], step["recs"])
    desc = (f"Step {step['number']} {step['title']}. Now: "
            + "; ".join(n["title"] for n in step["now"]) + ". Target: "
            + "; ".join(n["title"] for n in step["target"]) + ". Metric: " + step["metric"])
    return canvas(end + M - 8, f"Step {step['number']}: {step['title']} (now versus target)", desc,
                  "\n".join([head, left, right, bridge, foot]))


# --- Content (from STRATEGY_REPORT.md; references are repository paths) ---------------------

STEPS = [
    {
        "number": 1, "file": "step-1-hiring-signals.svg", "title": "Hiring signals", "state": "partial",
        "vision": "find posts that show a real hiring need from people who post varied professional content, "
                  "not from accounts that post 10-20 job ads a day.",
        "now": [
            {"kind": "now", "title": "Search cards with a recruiter-style suffix",
             "body": ["50 job-title cards; every query ends in \"hiring share resume\""],
             "ref": "src/jw/search_terms.py:10-26, :43-45"},
            {"kind": "now", "title": "Bulk export of LinkedIn posts",
             "body": ["Live run 2026-11-07: 2,000 posts from one Apify export"],
             "ref": "docs/implementation/LEAD_PIPELINE.md:37-41"},
            {"kind": "gap", "title": "A post is a lead only if its text holds an e-mail",
             "body": ["776 of 2,000 posts dropped as unparsed",
                      "Founders and EMs who write \"DM me\" or link a careers page are lost"],
             "ref": "src/jw/leads.py:107-109"},
            {"kind": "gap", "title": "Poster check counts display names, skips reposts",
             "body": ["439 reposts (36% of posts with an e-mail) are folded before the count, "
                      "so the strongest ad-stream signal never reaches it"],
             "ref": "src/jw/lead_filter.py:79-84; src/jw/leads.py:176-180"},
            {"kind": "gap", "title": "No content analysis",
             "body": ["No hiring ratio, copied templates, topic diversity or company link"],
             "ref": "src/jw/lead_filter.py:68-131"},
        ],
        "target": [
            {"kind": "new", "title": "Person-first query families",
             "body": ["\"my team\" hiring <stack>; \"I'm hiring\" <role>",
                      "Seniority and city terms cut the 47% experience and 65% location loss",
                      "Exclude \"our client\", C2C, \"multiple openings\""],
             "ref": "R7.2 (P1)"},
            {"kind": "reuse", "title": "URL capture through lib.fetch_post",
             "body": ["5-10 hand-picked posts a day from the candidate's own feed"],
             "ref": "lib/apify_client.py:106; R7.4 (P1)"},
            {"kind": "new", "title": "Signal classifier: hiring-intent weight",
             "bars": [("Own-team opening", 1.0), ("Team growth", 0.7), ("Role referral", 0.4),
                      ("Milestone, no role", 0.2), ("Agency multi-role ad", 0.2), ("Open-to-work post", 0.0)],
             "max": 1.0, "fmt": "{:.1f}", "ref": "R7.3 (P1): precision ≥ 85% on 100 labelled posts"},
            {"kind": "new", "title": "Keep leads without an e-mail",
             "body": ["Route becomes dm or apply_link instead of unparsed; hand over to step 2"],
             "ref": "R7.1 (P0)"},
        ],
        "metric": "Share of kept leads whose author is a hiring owner or in-house recruiter rises against the "
                  "day-30 baseline; signal classifier precision ≥ 85%.",
        "recs": "R7.1 keep no-e-mail leads (P0) · R7.5 drop signed-in scraping from docs (P0) · "
                "R7.2 person-first queries (P1) · R7.3 signal classifier (P1) · R7.4 URL capture (P1)",
    },
    {
        "number": 2, "file": "step-2-person.svg", "title": "The hiring person", "state": "missing",
        "vision": "know the name, designation, company, profile and hiring responsibility; classify the person "
                  "and rank the person, not only the job.",
        "now": [
            {"kind": "gap", "title": "Author is a display-name string",
             "body": ["Stored as recruiter on the post; no profile ID or URL"], "ref": "src/jw/leads.py:119"},
            {"kind": "gap", "title": "No title, employer or class",
             "body": ["Founder, EM, in-house recruiter and agency look identical"],
             "ref": "no table or code"},
            {"kind": "gap", "title": "Identity rule broken",
             "body": ["PRD: name-only matches cannot push a count over the limit; the code drops on them"],
             "ref": "docs/02-prd.md:860 vs src/jw/lead_filter.py:112"},
            {"kind": "rule", "title": "PRD anti-persona: no recruiter profiling",
             "body": ["Conflicts with the vision's background and style profile; resolve with the privacy "
                      "limits on the right"],
             "ref": "docs/02-prd.md:140-144"},
        ],
        "target": [
            {"kind": "new", "title": "people record",
             "body": ["Provider profile ID and URL, name, current title, employer, hiring posts, class, "
                      "evidence links"], "ref": "R16.2 (P1)"},
            {"kind": "new", "title": "author_history read method",
             "body": ["30-60 days of the author's posts, cached, small batches"], "ref": "R8.3 (P1)"},
            {"kind": "new", "title": "Authenticity features",
             "body": ["coverage_days, posts_per_week, hiring_ratio",
                      "template_similarity, role_spread, cross_author_copy",
                      "ownership_language, employer_match, topic_diversity"], "ref": "Report section 8.2"},
            {"kind": "new", "title": "Classes, first match wins",
             "body": ["ad_stream: hiring ratio ≥ 0.8 and ≥ 3 posts a week, or copied templates",
                      "agency_recruiter: ≥ 3 companies or \"our client\"",
                      "in_house_recruiter: recruiter title, employer match, one company",
                      "hiring_owner: founder, CTO, EM or lead; employer match; \"my team\"",
                      "hr_generalist; unknown when coverage < 14 days"], "ref": "Report section 8.3; R8.4 (P1)"},
            {"kind": "rule", "title": "Privacy limits",
             "body": ["Hiring-relevant fields only; no personality or style inference",
                      "Delete people with no interaction after 90 days"], "ref": "R10.4 (P1)"},
        ],
        "metric": "Classifier agrees with hand labels on ≥ 85% of 100 authors; ≥ 70% of sends go to hiring "
                  "owners or in-house recruiters.",
        "recs": "R8.1 identity by profile ID (P0) · R8.2 count reposts toward cadence (P0) · "
                "R8.5 replace the 3-4 posts a week rule (P0) · R8.3 author history (P1) · R8.4 classifier (P1)",
    },
    {
        "number": 3, "file": "step-3-contact.svg", "title": "Contact route", "state": "partial",
        "vision": "use only a legitimate public e-mail, record its source and confidence, never guess; with no "
                  "e-mail keep the lead with its post or apply link.",
        "now": [
            {"kind": "now", "title": "First e-mail found in the post text",
             "ref": "src/jw/leads.py:20, :107, :119"},
            {"kind": "gap", "title": "No address class",
             "body": ["A post listing press@ before careers@ sends to press"],
             "ref": "docs/02-prd.md:1204 (FR-EML-01), not built"},
            {"kind": "gap", "title": "No source, excerpt or confidence stored",
             "ref": "src/jw/leads.py:63-67"},
            {"kind": "now", "title": "Company taken from the e-mail domain",
             "body": ["Falls back to the author name for free mail"], "ref": "src/jw/leads.py:113"},
            {"kind": "gap", "title": "No e-mail means a dead end",
             "body": ["Feed and Naukri drafts are blocked as no_contact"], "ref": "src/jw/lead_drafts.py:76"},
        ],
        "target": [
            {"kind": "new", "title": "Route hierarchy, first that exists",
             "body": ["1. E-mail the person published for applications",
                      "2. Company recruiting inbox on an official page",
                      "3. Public professional contact the person published",
                      "4. Official apply link", "5. LinkedIn DM, written by hand"],
             "ref": "Report section 10.1; R10.3 (P2)"},
            {"kind": "new", "title": "Provenance on every route",
             "body": ["route, address_class, source_type", "source_url, captured_at, excerpt",
                      "domain_match; confidence high, medium or low"], "ref": "R10.1 (P0); R10.2 (P1)"},
            {"kind": "rule", "title": "\"Verified\" means published, nothing more",
             "body": ["Published by source S at URL U on date D, domain checked; never deliverable, read or "
                      "welcome"], "ref": "Report section 10.2"},
            {"kind": "never", "title": "Never",
             "body": ["Guess firstname@company", "Probe mailboxes", "Buy or scrape contact lists"],
             "ref": "docs/02-prd.md:183; R10.5 (P0)"},
        ],
        "metric": "100% of sends carry a source_url and excerpt; wrong-recipient replies = 0.",
        "recs": "R10.1 provenance (P0) · R10.5 written no-guess rule (P0) · R10.2 address class (P1) · "
                "R10.4 data minimisation (P1) · R10.3 company-page routes (P2)",
    },
    {
        "number": 4, "file": "step-4-opportunity.svg", "title": "Opportunity and score", "state": "partial",
        "vision": "extract title, experience, stack, location, salary and urgency, and separate explicit "
                  "requirements from assumptions.",
        "now": [
            {"kind": "now", "title": "Regex extraction",
             "body": ["Title from a role pattern, else \"Software Developer\"",
                      "Years from the first range in the text", "Location from an India city list"],
             "ref": "src/jw/leads.py:21-29, :116"},
            {"kind": "gap", "title": "Candidate's stack hard-coded",
             "body": ["35 skills, exclusions and the India rule live in source code"],
             "ref": "src/jw/lead_filter.py:25-40"},
            {"kind": "gap", "title": "Fit score is degenerate",
             "body": ["Skill overlap compares the candidate's list with itself",
                      "Probes: Java only = 100; eight matching skills = 100; Java plus six missing skills = 100"],
             "ref": "src/jw/lead_filter.py:57-61"},
            {"kind": "gap", "title": "Two scorers",
             "body": ["ranking.py (weights, confidence, explanations) is never used for leads"],
             "ref": "src/jw/ranking.py:143-210"},
        ],
        "target": [
            {"kind": "reuse", "title": "Requirement extraction task",
             "body": ["Explicit versus assumed, with source spans; existing extraction-* packet pattern"],
             "ref": "R16.3 (P1)"},
            {"kind": "reuse", "title": "lead-promote turns a lead into a jobs row",
             "body": ["Unlocks ranking, CV tasks, mail matching and metrics"],
             "ref": "src/jw/workspace.py:302; R16.1 (P0)"},
            {"kind": "rule", "title": "Hard gates before any score",
             "body": ["Suppressed; contacted within cooldown; scam indicator",
                      "Location ineligible; years above policy; ad_stream author"], "ref": "R9.3 (P1)"},
            {"kind": "new", "title": "10-factor score, weights out of 100",
             "bars": [("Hiring intent", 15), ("Skill overlap", 15), ("Author credibility", 12),
                      ("Freshness", 10), ("Experience fit", 10), ("Posting consistency", 8),
                      ("Professional relevance", 8), ("Company relevance", 8), ("Contact verification", 8),
                      ("Response likelihood", 6)],
             "max": 15, "ref": "Followers, likes and volume excluded; R9.2 (P1)"},
        ],
        "metric": "Score varies across kept leads at once (R9.1); after 100 sends the top score decile replies "
                  "at ≥ 2x the rate of the bottom half.",
        "recs": "R9.1 fix the overlap denominator (P0) · R16.1 lead-promote (P0) · R9.2 one 10-factor scorer (P1) · "
                "R9.3 hard gates (P1) · R16.3 extraction (P1) · R9.4 calibrate every 50 sends (P2)",
    },
    {
        "number": 5, "file": "step-5-resume.svg", "title": "Tailored resume", "state": "disconnected",
        "vision": "reorder and prioritise the candidate's real evidence, ATS-friendly, never invented, every claim "
                  "traceable, with a short why-this-resume note.",
        "now": [
            {"kind": "gap", "title": "One fixed PDF for the whole batch",
             "body": ["lead-approve and lead-send each take a single resume_path"],
             "ref": "src/jw/lead_queue.py:47, :81, :98"},
            {"kind": "reuse", "title": "Claims registry with provenance and sensitivity",
             "ref": "src/jw/workspace.py; src/jw/privacy.py (JW-03, JW-04)"},
            {"kind": "reuse", "title": "draft_cv accepts only exact claims or approved paraphrases",
             "ref": "src/jw/tasks.py:228-245; src/jw/semantics.py"},
            {"kind": "reuse", "title": "Review with severity floors; render and text gates",
             "ref": "src/jw/tasks.py:17-24; src/jw/verification.py"},
            {"kind": "gap", "title": "Never ready, never reached",
             "body": ["ready is always False; PDF marked PRIVATE DRAFT - NOT READY",
                      "Leads never become jobs, so draft_cv cannot run for them"],
             "ref": "src/jw/verification.py:239; src/jw/rendering.py:32"},
        ],
        "target": [
            {"kind": "rule", "title": "Owner decision: what \"ready\" means",
             "body": ["All gates passed plus candidate review; only then drop the watermark"],
             "ref": "R11.1 (P0)"},
            {"kind": "new", "title": "Three or four variants, built once",
             "body": ["backend-java, full-stack, frontend-react, mobile",
                      "Each through the existing gates; hash frozen"], "ref": "R11.2 (P1)"},
            {"kind": "new", "title": "Pick by role family; tailor only the best",
             "body": ["Per-lead draft_cv only when the score is ≥ 80"], "ref": "R11.4 (P2)"},
            {"kind": "new", "title": "Attachment per envelope",
             "body": ["Mixed-variant batches; hash checked at send; file named "
                      "<Candidate>_Resume_<Company>.pdf"], "ref": "R11.3 (P1); docs/02-prd.md:1225"},
            {"kind": "new", "title": "Why-this-resume note, shown at approval",
             "body": ["Variant and reason; supported 4 of 5 required (claim IDs); missing skills named, "
                      "never invented"], "ref": "Report section 11.5"},
        ],
        "metric": "Every send records its variant; reply rate by variant and interview rate of tailored versus "
                  "variant sends are compared.",
        "recs": "R11.1 ready decision (P0) · R11.2 variants (P1) · R11.3 per-envelope attachment (P1) · "
                "R11.4 per-lead CV for score ≥ 80 (P2) · R11.5 one truth store (P2)",
    },
    {
        "number": 6, "file": "step-6-email.svg", "title": "Personal e-mail", "state": "partial",
        "vision": "specific, concise, refers to the hiring signal; no stock phrases such as \"Please find my "
                  "resume attached\"; tailored resume attached.",
        "now": [
            {"kind": "gap", "title": "Writing standard hard-codes the candidate",
             "body": ["\"about 3 years of full stack work\" and \"resume attached\" sit in source code"],
             "ref": "src/jw/lead_drafts.py:30-34"},
            {"kind": "gap", "title": "Technology check knows 35 terms",
             "body": ["Probe: Kubernetes, GraphQL and Terraform, absent from the facts, passed as ready"],
             "ref": "src/jw/lead_drafts.py:62"},
            {"kind": "gap", "title": "Vision phrases are not banned",
             "body": ["\"perfect candidate\" and \"Please find my resume attached\" pass"],
             "ref": "src/jw/lead_drafts.py:23-26"},
            {"kind": "gap", "title": "Resume line is required",
             "body": ["A draft that does not say the resume is attached is blocked"],
             "ref": "src/jw/lead_drafts.py:75"},
            {"kind": "gap", "title": "False positive",
             "body": ["\"express my interest\" is blocked as the skill Express"],
             "ref": "src/jw/lead_filter.py:36-39, :53-54"},
        ],
        "target": [
            {"kind": "new", "title": "Anatomy, at most 120 words",
             "body": ["1. Signal: what they posted and when, in their words",
                      "2. Match: two or three facts with claim IDs, tied to their needs",
                      "3. Proof: one project or GitHub link", "4. Ask: one low-friction question",
                      "5. Opt-out: a one-word reply ends contact"], "ref": "R12.2 (P1)"},
            {"kind": "new", "title": "Checker",
             "body": ["Every technology token checked against the facts",
                      "Ban the vision phrases; require a signal reference",
                      "Drop the resume-line rule: the send step guarantees the attachment"],
             "ref": "R12.1 (P0)"},
            {"kind": "reuse", "title": "One follow-up in the same thread",
             "body": ["After 5-7 working days, with its own approval; cancelled by a reply"],
             "ref": "src/jw/followups.py (JW-15); R12.3 (P1)"},
            {"kind": "new", "title": "Drafting evals for jw",
             "body": ["No invention, banned phrases, signal reference"], "ref": "evals/run_evals.py; R12.4 (P2)"},
        ],
        "metric": "The probe drafts from section 1 are blocked; human reply rate is measured against the "
                  "pre-change baseline.",
        "recs": "R12.1 checker fixes (P0) · R12.2 signal-first anatomy (P1) · R12.3 threaded follow-up (P1) · "
                "R12.4 jw drafting evals (P2)",
    },
    {
        "number": 7, "file": "step-7-approval-tracking.svg", "title": "Approval and tracking", "state": "partial",
        "vision": "show post, person, contact, requirements, resume and e-mail; send only after approval; track "
                  "replies, bounces and follow-ups; never re-contact an opt-out.",
        "now": [
            {"kind": "now", "title": "lead-approve takes draft IDs in JSON",
             "body": ["Freezes subject, body and resume hash; 24-hour authorisation"],
             "ref": "src/jw/lead_queue.py:43-73"},
            {"kind": "gap", "title": "Caps skipped without schedule-set",
             "body": ["Up to 100 per call, 4 seconds apart, no daily ceiling"],
             "ref": "src/jw/schedule.py:88-92; src/jw/lead_queue.py:80, :93-94"},
            {"kind": "gap", "title": "Envelope has no job_id", "ref": "src/jw/lead_queue.py:64"},
            {"kind": "gap", "title": "Replies, bounces and opt-outs not linked",
             "body": ["They go to review: not suppressed, no follow-up, no metric"],
             "ref": "src/jw/mailsync.py:130-140; src/jw/metrics.py:35-40"},
            {"kind": "gap", "title": "Same person can get several e-mails",
             "body": ["Only identical content to one address is refused"], "ref": "src/jw/lead_queue.py:33-40"},
            {"kind": "gap", "title": "Revoked Google token prints a traceback",
             "ref": "src/jw/gmail.py:46; src/jw/cli.py:384-390"},
        ],
        "target": [
            {"kind": "reuse", "title": "job_id on every lead envelope",
             "body": ["create_envelope already accepts job_id"], "ref": "src/jw/actions.py:71; R16.1 (P0)"},
            {"kind": "new", "title": "Approval page on the loopback API",
             "body": ["Post, person and class, route provenance, requirements, resume preview, e-mail, "
                      "score explanation"], "ref": "src/jw/api.py; R16.4 (P1)"},
            {"kind": "rule", "title": "Default schedule",
             "body": ["15 a day in working hours; lead-send refuses without a schedule"],
             "ref": "R13.1 (P0); R13.2 (P1)"},
            {"kind": "reuse", "title": "mail-sync effects, once linked",
             "body": ["Bounce or opt-out: permanent suppression", "Reply: follow-up cancelled"],
             "ref": "src/jw/mailsync.py:205-216; R13.3 (P0)"},
            {"kind": "new", "title": "Contact cooldown",
             "body": ["30 days per person, 7 days per agency"], "ref": "Report section 9.2"},
            {"kind": "new", "title": "Weekly outcome report",
             "body": ["Replies by author class, resume variant and score decile"], "ref": "Report section 19"},
        ],
        "metric": "0 sends to opted-out or bounced addresses; human reply rate measurable for every send.",
        "recs": "R16.1 job_id bridge (P0) · R13.1 caps (P0) · R13.3 suppression (P0) · R13.4 token error (P0) · "
                "R13.7 live self-send (P0) · R16.4 approval page (P1)",
    },
]

OVERVIEW = [
    (1, "Hiring signals", "partial", "E-mail in the post text decides the lead", "Person-first queries and a signal classifier"),
    (2, "The person", "missing", "Display name only", "People record and author class"),
    (3, "Contact route", "partial", "First e-mail in the text, no source", "Route hierarchy with provenance"),
    (4, "Opportunity", "partial", "Regex fields; fit score always 100", "Explicit vs assumed; 10-factor score"),
    (5, "Resume", "disconnected", "One fixed PDF", "Gated variants chosen per lead"),
    (6, "E-mail", "partial", "Checker misses invented technologies", "Signal-first, claim-checked"),
    (7, "Approval, tracking", "partial", "No job_id, replies unlinked", "Linked outcomes, suppression, metrics"),
]
FUNNEL = [
    ("LinkedIn posts exported", 2000), ("with an e-mail in the text", 1224),
    ("new after repost folding", 785), ("opportunities (785 LinkedIn + 119 feed jobs)", 904),
    ("kept by lead-filter", 8), ("ready drafts after manual review", 2),
]


def overview_image():
    out = [f'<circle cx="{M + 22}" cy="{M + 22}" r="22" fill="{COLOR["brand"]}"/>',
           text(M + 22, M + 29, "0", 20, COLOR["surface"], 700, anchor="middle"),
           text(M + 60, M + 20, "Lead pipeline: vision versus code", SIZE["title"], COLOR["ink"], 700),
           text(M + 60, M + 46, "Seven steps from a hiring signal to a tracked reply. Every step has its own "
                "detailed image in STRATEGY_REPORT.md.", SIZE["subtitle"], COLOR["muted"])]
    gap = 2 * SPACE
    card_w = (W - 2 * M - 6 * gap) / 7
    y = M + 72
    inner = card_w - 2 * SPACE - 4

    def card_body(x, name, state, now, target):
        """Lays out one card's text; returns (svg parts, bottom y). Used to measure and to draw."""
        parts = []
        s_color, s_fill, s_border, s_label = STATE[state]
        cy = y + 2 * SPACE + 44
        for line in wrap(name, SIZE["node"], inner, "bold"):
            parts.append(text(x + SPACE + 4, cy, line, SIZE["node"], COLOR["ink"], 700))
            cy += LEADING["node"]
        for line in wrap(s_label, 9.5, inner, "bold"):
            svg, _ = chip(x + SPACE + 4, cy - 8, line, s_color, s_fill, s_border, size=9.5)
            parts.append(svg)
            cy += 22
        cy += 12
        for label, value, kind in (("NOW", now, "gap"), ("TARGET", target, "new")):
            parts.append(text(x + SPACE + 4, cy, label, SIZE["ref"], KIND[kind][0], 700, spacing="0.8"))
            cy += LEADING["body"]
            for line in wrap(value, SIZE["body"], inner):
                parts.append(text(x + SPACE + 4, cy, line, SIZE["body"], COLOR["text"]))
                cy += LEADING["body"]
            cy += SPACE
        return parts, cy

    card_h = max(card_body(0, *row[1:])[1] for row in OVERVIEW) - y + SPACE
    for i, (number, name, state, now, target) in enumerate(OVERVIEW):
        x = M + i * (card_w + gap)
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{card_w:.1f}" height="{card_h}" rx="{RADIUS["node"]}" '
                   f'fill="{COLOR["panel"]}" stroke="{COLOR["border"]}"/>')
        out.append(f'<circle cx="{x + 2 * SPACE + 10:.1f}" cy="{y + 2 * SPACE + 10}" r="12" fill="{COLOR["brand"]}"/>')
        out.append(text(x + 2 * SPACE + 10, y + 2 * SPACE + 15, str(number), 13, COLOR["surface"], 700, anchor="middle"))
        out.extend(card_body(x, name, state, now, target)[0])
        if i < 6:
            ax = x + card_w + 2
            out.append(f'<path d="M{ax:.1f},{y + 30} l{gap - 4},0" stroke="{COLOR["line"]}" stroke-width="2"/>'
                       f'<path d="M{ax + gap - 8:.1f},{y + 25} l6,5 l-6,5 Z" fill="{COLOR["line"]}"/>')
    # Funnel
    fy = y + card_h + 4 * SPACE
    out.append(text(M, fy, "Live run, 2026-11-07: where 2,000 posts went", 16, COLOR["ink"], 700))
    out.append(text(W - M, fy, "docs/implementation/LEAD_PIPELINE.md:37-46, :60-62, :80-85", SIZE["ref"],
                    COLOR["muted"], face=MONO, anchor="end"))
    fy += 3 * SPACE
    label_w, track_x = 330, M + 330
    track_w = W - 2 * M - label_w - 70
    for label, value in FUNNEL:
        out.append(text(M, fy + 5, label, SIZE["body"] + 0.5, COLOR["text"]))
        out.append(f'<rect x="{track_x}" y="{fy - 8}" width="{track_w}" height="16" rx="8" fill="{COLOR["track"]}"/>')
        out.append(f'<rect x="{track_x}" y="{fy - 8}" width="{max(4, track_w * value / 2000):.1f}" height="16" '
                   f'rx="8" fill="{COLOR["brand"]}"/>')
        out.append(text(W - M, fy + 5, f"{value:,}", 13, COLOR["ink"], 700, anchor="end"))
        fy += 28
    fy += SPACE
    out.append(text(M, fy + 6, "2 of 2,000 posts became a sendable e-mail: a yield of 0.1%.", SIZE["body"] + 0.5,
                    COLOR["ink"], 600))
    fy += 3 * SPACE
    out.append(legend(M, fy))
    desc = ("Seven pipeline steps with their state: " + "; ".join(f"{n} {name} {STATE[s][3].lower()}"
                                                                  for n, name, s, _, _ in OVERVIEW)
            + ". Funnel from the 2026-11-07 run: " + ", ".join(f"{label} {value}" for label, value in FUNNEL) + ".")
    return canvas(fy + 20 + M, "Lead pipeline: vision versus code", desc, "\n".join(out))


# --- Animated flows (README) ---------------------------------------------------------------
# CSS animation inside the SVG: GitHub shows it through <img>, scripts never run. Each stage is lit
# in turn on one shared clock; a dot runs along each connector. A static caption is shown when the
# viewer prefers reduced motion or does not animate, so the image always reads correctly.

TAG = {"jw": (*KIND["now"][:2], "JW"), "claude": (*KIND["reuse"][:2], "CLAUDE"),
       "you": (*KIND["rule"][:2], "YOU"), "gmail": (*KIND["new"][:2], "GMAIL")}


def animated_flow(title, subtitle, stages, cols, static, seconds=2.5):
    n = len(stages)
    gap_x, gap_y = 6 * SPACE, 6 * SPACE
    node_w = (W - 2 * M - (cols - 1) * gap_x) / cols
    inner = node_w - 4 * SPACE

    def body(stage, x, y):
        parts, cy = [], y + 2 * SPACE + 10
        accent, tint, label = TAG[stage["tag"]]
        parts.append(f'<circle cx="{x + 2 * SPACE + 10:.1f}" cy="{cy:.1f}" r="13" fill="{COLOR["brand"]}"/>')
        parts.append(text(x + 2 * SPACE + 10, cy + 5, str(stage["n"]), 13, COLOR["surface"], 700, anchor="middle"))
        svg, _ = chip(x + node_w - 2 * SPACE, cy - 9, label, accent, tint, anchor="end")
        parts.append(svg)
        cy += 13 + 2 * SPACE + 6
        for line in wrap(stage["title"], SIZE["node"] + 2, inner, "bold"):
            parts.append(text(x + 2 * SPACE, cy, line, SIZE["node"] + 2, COLOR["ink"], 700))
            cy += LEADING["node"] + 2
        for line in wrap(stage["cmd"], SIZE["ref"] + 0.5, inner, "mono"):
            parts.append(text(x + 2 * SPACE, cy, line, SIZE["ref"] + 0.5, COLOR["brand"], 600, face=MONO))
            cy += LEADING["ref"]
        cy += 6
        for line in wrap(stage["detail"], SIZE["body"], inner):
            parts.append(text(x + 2 * SPACE, cy, line, SIZE["body"], COLOR["text"]))
            cy += LEADING["body"]
        return parts, cy

    top = M + 76
    node_h = max(body(s, 0, 0)[1] for s in stages) + 2 * SPACE
    rows = -(-n // cols)
    pos = []
    for i in range(n):
        r, c = divmod(i, cols)
        c = c if r % 2 == 0 else cols - 1 - c   # snake: the next row runs back the other way
        pos.append((M + c * (node_w + gap_x), top + r * (node_h + gap_y)))

    cycle = n * seconds
    share = 100 / n
    css = [f"@keyframes on{{0%{{opacity:0}}{1.2:.2f}%{{opacity:1}}{share - 1.2:.2f}%{{opacity:1}}"
           f"{share:.2f}%{{opacity:0}}100%{{opacity:0}}}}",
           "@keyframes hide{0%,100%{opacity:0}}",
           "@keyframes grow{0%{transform:scaleX(0)}100%{transform:scaleX(1)}}",
           f".hl,.cap{{opacity:0;animation:on {cycle:g}s linear infinite}}",
           f".bar{{transform-box:fill-box;transform-origin:left center;animation:grow {cycle:g}s linear infinite}}",
           ".st{animation:hide 1s infinite}",
           ".dot{opacity:0}",
           "@media (prefers-reduced-motion: reduce){.hl,.cap,.dot,.bar{animation:none!important}"
           ".cap,.dot{opacity:0}.st{animation:none;opacity:1}}"]
    out = [text(M, M + 20, title, SIZE["title"], COLOR["ink"], 700)]
    for k, line in enumerate(wrap(subtitle, SIZE["subtitle"], W - 2 * M)):
        out.append(text(M, M + 46 + 20 * k, line, SIZE["subtitle"], COLOR["muted"]))
    # Connectors and their travelling dots.
    for i in range(n - 1):
        (x1, y1), (x2, y2) = pos[i], pos[i + 1]
        if y1 == y2:
            right = x2 > x1
            sx = x1 + node_w if right else x1
            ex = x2 if right else x2 + node_w
            sy = ey = y1 + node_h / 2
            head = (f'M{ex - 7 if right else ex + 7:.1f},{ey - 5:.1f} l{7 if right else -7},5 '
                    f'l{-7 if right else 7},5 Z')
        else:
            sx = ex = x1 + node_w / 2
            sy, ey = y1 + node_h, y2
            head = f'M{ex - 5:.1f},{ey - 7:.1f} l5,7 l5,-7 Z'
        out.append(f'<path d="M{sx:.1f},{sy:.1f} L{ex:.1f},{ey:.1f}" stroke="{COLOR["line"]}" stroke-width="2"/>'
                   f'<path d="{head}" fill="{COLOR["line"]}"/>')
        a = (i + 0.55) * share
        b = (i + 0.95) * share
        dx, dy = ex - sx, ey - sy
        css.append(f"@keyframes m{i}{{0%,{a:.2f}%{{opacity:0;transform:translate(0px,0px)}}"
                   f"{a + 0.01:.2f}%{{opacity:1;transform:translate(0px,0px)}}"
                   f"{b:.2f}%{{opacity:1;transform:translate({dx:.1f}px,{dy:.1f}px)}}"
                   f"{b + 0.5:.2f}%,100%{{opacity:0;transform:translate({dx:.1f}px,{dy:.1f}px)}}}}")
        css.append(f".d{i}{{animation:m{i} {cycle:g}s linear infinite}}")
        out.append(f'<circle class="dot d{i}" cx="{sx:.1f}" cy="{sy:.1f}" r="6" fill="{COLOR["brand"]}"/>')
    # Stage cards with their highlight ring.
    for i, stage in enumerate(stages):
        x, y = pos[i]
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w:.1f}" height="{node_h:.1f}" '
                   f'rx="{RADIUS["node"]}" fill="{COLOR["panel"]}" stroke="{COLOR["border"]}"/>')
        out.append(f'<rect class="hl" style="animation-delay:{i * seconds:g}s" x="{x:.1f}" y="{y:.1f}" '
                   f'width="{node_w:.1f}" height="{node_h:.1f}" rx="{RADIUS["node"]}" fill="#EEF4FF" '
                   f'stroke="{COLOR["brand"]}" stroke-width="3"/>')
        out.extend(body(stage, x, y)[0])
    # Caption panel: one caption per stage on the same clock, plus the static fallback.
    cy = top + rows * node_h + (rows - 1) * gap_y + 4 * SPACE
    lines_max = max(len(wrap(f'{s["n"]}. {s["caption"]}', SIZE["subtitle"] + 1, W - 2 * M - 4 * SPACE))
                    for s in stages)
    static_lines = wrap(static, SIZE["subtitle"] + 1, W - 2 * M - 4 * SPACE)
    cap_h = 3 * SPACE + 22 * max(lines_max, len(static_lines)) + 10
    out.append(f'<rect x="{M}" y="{cy}" width="{W - 2 * M}" height="{cap_h}" rx="{RADIUS["node"]}" '
               f'fill="{COLOR["panel"]}" stroke="{COLOR["border"]}"/>')
    for i, stage in enumerate(stages):
        group = [text(M + 2 * SPACE, cy + 3 * SPACE + 6 + 22 * k, line, SIZE["subtitle"] + 1,
                      COLOR["ink"])
                 for k, line in enumerate(wrap(f'{stage["n"]}. {stage["caption"]}', SIZE["subtitle"] + 1,
                                               W - 2 * M - 4 * SPACE))]
        out.append(f'<g class="cap" style="animation-delay:{i * seconds:g}s">' + "".join(group) + "</g>")
    out.append('<g class="st">' + "".join(text(M + 2 * SPACE, cy + 3 * SPACE + 6 + 22 * k, line,
                                               SIZE["subtitle"] + 1, COLOR["ink"])
                                          for k, line in enumerate(static_lines)) + "</g>")
    by = cy + cap_h + 2 * SPACE
    out.append(f'<rect x="{M}" y="{by}" width="{W - 2 * M}" height="6" rx="3" fill="{COLOR["track"]}"/>')
    out.append(f'<rect class="bar" x="{M}" y="{by}" width="{W - 2 * M}" height="6" rx="3" fill="{COLOR["brand"]}"/>')
    legend_y = by + 4 * SPACE
    x = M
    for key in [k for k in TAG if any(s["tag"] == k for s in stages)]:
        accent, tint, label = TAG[key]
        svg, width = chip(x, legend_y - 12, label, accent, tint)
        out.append(svg)
        words = {"jw": "jw command", "claude": "Claude writes", "you": "your decision", "gmail": "Gmail call"}[key]
        out.append(text(x + width + SPACE, legend_y + 1, words, SIZE["ref"] + 1, COLOR["muted"]))
        x += width + SPACE + len(words) * (SIZE["ref"] + 1) * GLYPH["sans"] + 4 * SPACE
    height = legend_y + 2 * SPACE + M
    desc = title + ". " + " ".join(f'Step {s["n"]}, {s["title"]} ({s["cmd"]}): {s["caption"]}' for s in stages)
    svg = canvas(height, title, desc, "<style>" + "".join(css) + "</style>\n" + "\n".join(out))
    return svg


PIPELINE_ANIMATED = [
    {"n": 1, "tag": "jw", "cmd": "lead-fetch / lead-import", "title": "Bring in job posts",
     "detail": "RemoteOK, Himalayas, Naukri invites in Gmail, LinkedIn post exports",
     "caption": "Parsers pull out the role, company, location and years (and skills, from the feeds and "
                "Naukri). Only LinkedIn posts carry a recruiter e-mail. A repost (same e-mail, same role) is "
                "stored once."},
    {"n": 2, "tag": "jw", "cmd": "lead-filter", "title": "Keep what fits",
     "detail": "Posted within 48 h, at most 5 years asked, role, location and already-applied rules",
     "caption": "Every dropped lead gets a reason code. Each kept lead gets a 0-100 fit score with its "
                "matched skills, and a link where the source gives one."},
    {"n": 3, "tag": "jw", "cmd": "lead-draft-packet", "title": "Build the brief",
     "detail": "The post, the recruiter address, your facts file and the writing standard",
     "caption": "Your facts file is the only source of your claims. Keep it outside the repository; jw "
                "reads it from the path you pass each time and stores neither the file nor the path."},
    {"n": 4, "tag": "claude", "cmd": "Claude", "title": "Write the e-mail",
     "detail": "Subject and body from the packet, under 180 words",
     "caption": "Claude writes the subject and body from the packet when you ask it. Nothing is sent here."},
    {"n": 5, "tag": "jw", "cmd": "lead-draft-submit", "title": "Check the draft",
     "detail": "Blocks unsupported figures and known technologies, unasked salary or notice, stock phrases",
     "caption": "The draft is ready or blocked, with reasons. A lead with no recruiter e-mail is blocked as "
                "no_contact: apply through its link, or the Naukri invite, instead."},
    {"n": 6, "tag": "you", "cmd": "lead-approve", "title": "You approve a batch",
     "detail": "Each ready draft is frozen with your resume's hash for 24 hours",
     "caption": "Your approval is the only way a draft becomes sendable. Drafts that are not ready are "
                "skipped with a reason."},
    {"n": 7, "tag": "gmail", "cmd": "lead-send", "title": "Send once",
     "detail": "Gmail, 4 s apart, resume attached; a lost response is never resent",
     "caption": "Each approval is spent once. A resume that changed since approval is refused before Gmail "
                "is called."},
    {"n": 8, "tag": "gmail", "cmd": "lead-reconcile / mail-sync", "title": "Confirm and follow up",
     "detail": "Settle unknown sends from Sent; read replies and bounces",
     "caption": "Unknown sends are matched in your Sent folder by recipient, subject and the X-JW-Action-Id "
                "header. mail-sync reads replies and bounces."},
]

SEND_ANIMATED = [
    {"n": 1, "tag": "you", "cmd": "lead-approve", "title": "Freeze the e-mail",
     "detail": "Recipient, subject, body and resume hash in one authorisation, valid 24 h",
     "caption": "Approval freezes exactly what will be sent. If the resume file changes afterwards, the "
                "send is refused."},
    {"n": 2, "tag": "jw", "cmd": "lead-send", "title": "Reserve the attempt",
     "detail": "Recipient, content and resume must match the approval; it is spent before Gmail is called",
     "caption": "The attempt is recorded before the provider call, so a crash cannot lead to a second send."},
    {"n": 3, "tag": "gmail", "cmd": "Gmail API", "title": "Send",
     "detail": "One call, resume attached, action ID in the X-JW-Action-Id header",
     "caption": "Accepted: the draft is marked sent and the attempt keeps the Gmail thread ID. Rejected: the "
                "attempt is marked failed with the reason; the draft stays ready but its approval is spent."},
    {"n": 4, "tag": "gmail", "cmd": "timeout", "title": "Response lost",
     "detail": "Gmail may have sent it, but jw never heard back",
     "caption": "A timeout or dropped connection marks the attempt unknown, not failed."},
    {"n": 5, "tag": "jw", "cmd": "lead-send (next run)", "title": "Never resent",
     "detail": "The approval is already spent, so the draft is skipped",
     "caption": "Running lead-send again cannot send a duplicate: an unknown attempt is never retried."},
    {"n": 6, "tag": "jw", "cmd": "lead-reconcile", "title": "Settle from Sent",
     "detail": "Search Sent by recipient and subject, match the header, mark it sent",
     "caption": "If the e-mail is in your Sent folder with the same action ID, it is marked sent. If not, it "
                "stays unknown, and lead-send refuses every other e-mail (unresolved_unknown) until it is "
                "settled."},
]


def main():
    (OUT / "overview-pipeline.svg").write_text(overview_image(), encoding="utf-8")
    for step in STEPS:
        (OUT / step["file"]).write_text(step_image(step), encoding="utf-8")
    (OUT / "pipeline-animated.svg").write_text(animated_flow(
        "From job post to recruiter e-mail", "What jw does today, one step at a time. jw and its database run on "
        "your machine; Claude reads the packet when it writes; no e-mail is sent until you approve.", PIPELINE_ANIMATED, 4,
        "Eight steps: bring in posts, filter, build the brief, Claude writes, check figures, technologies and "
        "wording, you approve, send once through Gmail, then confirm from Sent and read replies."), encoding="utf-8")
    (OUT / "send-once-animated.svg").write_text(animated_flow(
        "How lead-send sends each e-mail once", "The path when Gmail's response is lost: the e-mail is never "
        "sent twice, and lead-reconcile settles it from your Sent folder.", SEND_ANIMATED, 3,
        "Approval freezes the e-mail; the attempt is reserved before Gmail is called; a lost response is "
        "marked unknown and never resent; lead-reconcile settles it from Sent."), encoding="utf-8")
    print("Wrote", 3 + len(STEPS), "SVG files to", OUT)


if __name__ == "__main__":
    main()
