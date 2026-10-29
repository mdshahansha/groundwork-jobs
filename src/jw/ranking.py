"""Versioned pure ranking arithmetic; no network, inference or side effects."""

from calendar import monthrange
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP, localcontext
from functools import wraps
import re

from .contracts import fields, require

WEIGHTS = {"required": 35, "title": 15, "preferred": 10, "domain": 10,
           "location": 10, "salary": 10, "freshness": 5, "contact": 5}
STATES = {"supported": Decimal(1), "partial": Decimal("0.5"),
          "unsupported": Decimal(0), "unknown": Decimal("0.25")}
HALF = Decimal("0.5")


def fixed_precision(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=28)):
            return function(*args, **kwargs)
    return wrapped


def number(value, maximum=1_000_000_000):
    require(type(value) in (int, float, str, Decimal), "invalid_schema", "Expected a finite number.")
    require(len(str(value)) <= 100, "invalid_schema", "Numeric representation exceeds 100 characters.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        require(False, "invalid_schema", "Expected a finite number.")
    require(result.is_finite() and 0 <= result <= maximum, "invalid_schema", "Number is outside allowed bounds.")
    require(abs(result.as_tuple().exponent) <= 12, "invalid_schema", "Numeric exponent exceeds supported precision.")
    return result


def day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
            "invalid_time", "Use a full ISO calendar date.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        require(False, "invalid_time", "Invalid calendar date.")


@fixed_precision
def skill_mean(states):
    require(isinstance(states, list) and len(states) <= 100, "invalid_schema", "Expected at most 100 skill states.")
    for state in states:
        require(isinstance(state, str) and state in STATES, "invalid_schema", "Unknown skill state.")
    if not states:
        return HALF, Decimal(0)
    return (sum((STATES[s] for s in states), Decimal(0)) / len(states),
            Decimal(sum(s != "unknown" for s in states)) / len(states))


@fixed_precision
def annual_salary(value):
    if value is None:
        return None
    fields(value, {"min", "max", "currency", "basis", "period"}, {"hours_per_week"})
    require(isinstance(value["currency"], str) and re.fullmatch(r"[A-Z]{3}", value["currency"]),
            "invalid_schema", "Currency must be a three-letter uppercase code.")
    require(value["basis"] in ("base", "ctc", "total") and value["period"] in ("year", "month", "hour"),
            "invalid_schema", "Unknown pay basis or period.")
    low, high = number(value["min"]), number(value["max"])
    require(low <= high, "invalid_schema", "Salary bounds are reversed.")
    hours = value.get("hours_per_week")
    if hours is not None:
        hours = number(hours, 168)
        require(hours > 0, "invalid_schema", "Working hours must be positive.")
    if value["period"] == "hour" and hours is None:
        return None
    factor = {"year": Decimal(1), "month": Decimal(12), "hour": (hours or 0) * 52}[value["period"]]
    return low * factor, high * factor, value["currency"], value["basis"]


@fixed_precision
def salary_fit(candidate, job):
    left, right = annual_salary(candidate), annual_salary(job)
    if left is None or right is None or left[2:] != right[2:]:
        return HALF, Decimal(0)
    low, high = left[:2]
    if low == high:
        return Decimal(int(right[0] <= low <= right[1])), Decimal(1)
    overlap = max(Decimal(0), min(high, right[1]) - max(low, right[0]))
    return overlap / (high - low), Decimal(1)


@fixed_precision
def experience(intervals, as_of):
    """Return conservative union days/years; no inference from missing dates."""
    today = day(as_of)
    require(isinstance(intervals, list) and len(intervals) <= 200, "invalid_schema", "Expected at most 200 employment intervals.")

    def boundary(value, start):
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
            first = day(value + "-01")
            return first.replace(day=monthrange(first.year, first.month)[1]) if start else first
        return day(value)

    spans = []
    for item in intervals:
        fields(item, {"start", "end"})
        start = boundary(item["start"], True)
        end = today if item["end"] is None else boundary(item["end"], False)
        end = min(end, today)
        if end > start:
            spans.append((start, end))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    days = sum((end - start).days for start, end in merged)
    years = (Decimal(days) / Decimal("365.25")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return {"days": days, "years": float(years), "calculation_date": as_of}


def experience_band(years, minimum=None, maximum=None):
    low = number(minimum, 100) if minimum is not None else None
    high = number(maximum, 100) if maximum is not None else None
    require(low is None or high is None or low <= high, "invalid_schema", "Experience bounds are reversed.")
    if years is None:
        return "unknown"
    value = number(years, 100)
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "within"


@fixed_precision
def score(required, preferred, assessment, as_of):
    fields(assessment, {"title_alias_match", "seniority_distance", "domain", "location",
                        "location_eligible", "candidate_salary", "job_salary", "posted_on", "contact"},
           {"freshness_window_days"})
    today = day(as_of)
    alias, distance = assessment["title_alias_match"], assessment["seniority_distance"]
    require(alias is None or type(alias) is bool, "invalid_schema", "Title alias match must be boolean or null.")
    require(distance is None or (type(distance) is int and 0 <= distance <= 20),
            "invalid_schema", "Seniority distance must be 0..20 or null.")
    eligible = assessment["location_eligible"]
    require(eligible is None or type(eligible) is bool, "invalid_schema", "Location eligibility must be boolean or null.")
    domain, location, contact = (assessment[k] for k in ("domain", "location", "contact"))
    require(isinstance(domain, str) and domain in STATES, "invalid_schema", "Unknown domain assessment.")
    require(location in ("exact", "relocation", "unclear", "mismatch"), "invalid_schema", "Unknown location fit.")
    require(contact in ("official", "named_recruiter", "other", "unknown"), "invalid_schema", "Unknown contact quality.")
    title = (Decimal(0), Decimal(1)) if alias is False else (
        (HALF, Decimal(0)) if alias is None or distance is None else
        (Decimal(1) if distance == 0 else HALF if distance == 1 else Decimal(0), Decimal(1)))
    window = assessment.get("freshness_window_days", 30)
    require(type(window) is int and 1 <= window <= 3650, "invalid_schema", "Freshness window must be 1..3650 days.")
    posted = assessment["posted_on"]
    age = None if posted is None else (today - day(posted)).days
    freshness = (HALF, Decimal(0)) if age is None or age < 0 else (
        max(Decimal(0), Decimal(1) - Decimal(age) / window), Decimal(1))
    components = {
        "required": skill_mean(required), "title": title, "preferred": skill_mean(preferred),
        "domain": (HALF if domain == "unknown" else STATES[domain], Decimal(domain != "unknown")),
        "location": ({"exact": Decimal(1), "relocation": Decimal("0.6"), "unclear": HALF, "mismatch": Decimal(0)}[location], Decimal(location != "unclear")),
        "salary": salary_fit(assessment["candidate_salary"], assessment["job_salary"]),
        "freshness": freshness,
        "contact": ({"official": Decimal(1), "named_recruiter": Decimal("0.6"), "other": Decimal("0.3"), "unknown": HALF}[contact], Decimal(contact != "unknown")),
    }
    def rounded(value):
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    total = sum(value * WEIGHTS[key] for key, (value, _) in components.items())
    confidence = sum(known * WEIGHTS[key] for key, (_, known) in components.items())
    exclusions = ["LOCATION_MISMATCH"] if eligible is False else []
    return {"version": "calculations@1", "weights": "weights@1", "score": rounded(total),
            "confidence": rounded(confidence), "calculation_date": as_of,
            "components": {key: {"value": rounded(value), "weight": WEIGHTS[key], "known": rounded(known)}
                           for key, (value, known) in components.items()},
            "exclusions": exclusions, "recommendation": "skip" if exclusions else "review",
            "credibility": "unassessed", "availability": "unverified",
            "label": "Relevance to your profile (0-100). Not an employer ATS score or hiring probability."}


@fixed_precision
def order_rankings(results):
    """Stable shortlist order, with hard-excluded jobs after eligible/unknown jobs."""
    require(isinstance(results, list) and len(results) <= 10000, "invalid_schema", "Ranking batch exceeds its limit.")
    seen = set()
    for item in results:
        require(isinstance(item, dict) and isinstance(item.get("job_id"), str),
                "invalid_schema", "Ranking needs a job ID.")
        require(item["job_id"] not in seen, "invalid_schema", "Duplicate job in ranking batch.")
        seen.add(item["job_id"])
        number(item.get("score"), 100)
        require(isinstance(item.get("exclusions"), list), "invalid_schema", "Ranking needs explicit exclusions.")
    return sorted(results, key=lambda item: (bool(item["exclusions"]), -Decimal(str(item["score"])), item["job_id"]))
