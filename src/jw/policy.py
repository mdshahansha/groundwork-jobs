"""Versioned ranking policy: validate, normalise, hash. No defaults are hidden.

The policy is the ranking subset of FR-CFG-01. A ranking pins the hash of the policy
that produced it; activating a different policy marks earlier rankings outdated.
Unknown keys are errors with the field path and a closest-match suggestion.
"""

import difflib
import re

from .contracts import WorkspaceError, canonical, digest

POLICY_SCHEMA = "ranking-policy@1"
# weights@0 (legacy job-skill set) needs experience and education components that
# calculations@2 does not compute; it is refused rather than silently approximated.
WEIGHT_SETS = {"weights@1": {"required": 35, "title": 15, "preferred": 10, "domain": 10,
                             "location": 10, "salary": 10, "freshness": 5, "contact": 5}}
SHAPE = {
    "schema": None,
    "weights": None,
    "relevance_threshold": None,
    "freshness": {"max_age_days": None},
    "companies": {"deny": None},
    "skills": {"excluded_terms": None},
    "location": {"countries": None, "remote": None},
    "eligibility": {"country": None, "authorisations_not_held": None, "credentials_absent": None},
    "history": {"exclude_applied_within_days": None},
}
COUNTRY = re.compile(r"[A-Z]{2}")


def _fail(path, message):
    raise WorkspaceError("policy_invalid", f"{path}: {message}")


def _keys(value, shape, path):
    if not isinstance(value, dict):
        _fail(path or "$", "expected an object")
    for key in value:
        if key not in shape:
            close = difflib.get_close_matches(str(key), list(shape), n=1)
            hint = f' Did you mean "{close[0]}"?' if close else ""
            _fail(f"{path}.{key}" if path else str(key), "unknown key." + hint)
    for key in shape:
        if key not in value:
            _fail(f"{path}.{key}" if path else key, "required key is missing")
        if isinstance(shape[key], dict):
            _keys(value[key], shape[key], f"{path}.{key}" if path else key)


def _integer(value, low, high, path):
    if type(value) is not int or not low <= value <= high:
        _fail(path, f"expected an integer {low}..{high}")
    return value


def _terms(value, path, limit=200, pattern=None):
    if not isinstance(value, list) or len(value) > limit:
        _fail(path, f"expected a list of at most {limit} strings")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or len(item) > 200:
            _fail(f"{path}[{index}]", "expected a non-empty string of at most 200 characters")
        item = " ".join(item.split())
        if pattern and not pattern.fullmatch(item):
            _fail(f"{path}[{index}]", "expected an ISO 3166-1 alpha-2 uppercase code")
        result.append(item if pattern else item.casefold())
    return sorted(set(result))


def validate(policy):
    """Return the normalised policy and its hash, or raise policy_invalid naming the field path."""
    _keys(policy, SHAPE, "")
    if policy["schema"] != POLICY_SCHEMA:
        _fail("schema", f'expected "{POLICY_SCHEMA}"')
    if policy["weights"] not in WEIGHT_SETS:
        _fail("weights", "unsupported weight set; calculations@2 supports weights@1 only")
    location, eligibility = policy["location"], policy["eligibility"]
    if location["remote"] not in ("only", "allowed", "no"):
        _fail("location.remote", 'expected "only", "allowed" or "no"')
    countries = _terms(location["countries"], "location.countries", 250, COUNTRY)
    if not countries and location["remote"] == "no":
        _fail("location", "at least one country is required when remote is no")
    country = eligibility["country"]
    if country is not None and not (isinstance(country, str) and COUNTRY.fullmatch(country)):
        _fail("eligibility.country", "expected an ISO 3166-1 alpha-2 uppercase code or null")
    normalised = {
        "schema": POLICY_SCHEMA,
        "weights": policy["weights"],
        "relevance_threshold": _integer(policy["relevance_threshold"], 0, 100, "relevance_threshold"),
        "freshness": {"max_age_days": _integer(policy["freshness"]["max_age_days"], 1, 90, "freshness.max_age_days")},
        "companies": {"deny": _terms(policy["companies"]["deny"], "companies.deny")},
        "skills": {"excluded_terms": _terms(policy["skills"]["excluded_terms"], "skills.excluded_terms")},
        "location": {"countries": countries, "remote": location["remote"]},
        "eligibility": {"country": country,
                        "authorisations_not_held": _terms(eligibility["authorisations_not_held"],
                                                          "eligibility.authorisations_not_held"),
                        "credentials_absent": _terms(eligibility["credentials_absent"],
                                                     "eligibility.credentials_absent")},
        "history": {"exclude_applied_within_days": _integer(
            policy["history"]["exclude_applied_within_days"], 0, 365, "history.exclude_applied_within_days")},
    }
    return normalised, "pol_" + digest(normalised)


def phrase_in(phrase, text):
    """Case-insensitive whole-phrase match; whitespace runs compare equal."""
    pattern = r"\s+".join(re.escape(part) for part in phrase.casefold().split())
    return bool(pattern) and re.search(r"(?<!\w)" + pattern + r"(?!\w)", text.casefold()) is not None


def hard_exclusions(policy, job, applied_days_ago):
    """FR-RNK-01 exclusions that the stored policy and job state explicitly. Unknowns never exclude.

    Each result names the code, the rule that fired and the value that matched (US-RNK-02).
    `applied_days_ago` is the age in days of the most recent manual application, or None.
    """
    found = []
    company = " ".join(job["company"].split()).casefold()
    if company in policy["companies"]["deny"]:
        found.append({"code": "COMPANY_DENIED", "rule": "companies.deny", "value": job["company"]})
    texts = [job["title"], *job["requirements"], *job.get("preferred_requirements", [])]
    for term in policy["skills"]["excluded_terms"]:
        if any(phrase_in(term, text) for text in texts):
            found.append({"code": "EXCLUDED_TERM", "rule": "skills.excluded_terms", "value": term})
    regions, country = job.get("remote_regions"), policy["eligibility"]["country"]
    if regions and country is not None and country not in regions:
        found.append({"code": "REMOTE_REGION_MISMATCH", "rule": "job.remote_regions",
                      "value": ",".join(regions) + " excludes " + country})
    for item in job.get("required_authorisations", []):
        if " ".join(item.split()).casefold() in policy["eligibility"]["authorisations_not_held"]:
            found.append({"code": "AUTHORISATION_NOT_HELD", "rule": "eligibility.authorisations_not_held",
                          "value": item})
    for item in job.get("mandatory_credentials", []):
        if " ".join(item.split()).casefold() in policy["eligibility"]["credentials_absent"]:
            found.append({"code": "MANDATORY_CREDENTIAL_MISSING", "rule": "eligibility.credentials_absent",
                          "value": item})
    window = policy["history"]["exclude_applied_within_days"]
    if applied_days_ago is not None and window and applied_days_ago < window:
        found.append({"code": "ALREADY_APPLIED", "rule": "history.exclude_applied_within_days",
                      "value": f"{applied_days_ago} days ago"})
    return found


def describe(policy, policy_hash):
    return {"policy_hash": policy_hash, "policy": policy, "canonical_bytes": len(canonical(policy).encode())}
