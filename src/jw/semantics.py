"""Deterministic paraphrase guard. Conservative lexical invariants, not semantic entailment.

A paraphrase may reorder or reword a supported claim. It may not change a quantity,
introduce a named entity, flip a negation, strengthen scope or seniority, or add a
credential. Passing the guard is necessary, never sufficient: only a candidate-approved
paraphrase is accepted in model output. Findings are reason codes and never echo text.
"""

import re

GUARD_VERSION = "guard-1"

NUMBER = re.compile(r"[$€£₹]?\d+(?:[.,]\d+)*(?:\s?(?:%|percent|k|m|bn|ms|s|x|h|hours|years?|months?)(?![A-Za-z]))?",
                    re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z+#'-]*")
NEGATIONS = {"not", "no", "never", "without", "none", "nor", "cannot", "neither"}
# Words that raise seniority, ownership or scope beyond what a claim states.
ESCALATION = {"led", "lead", "leading", "managed", "manager", "managing", "owned", "owner", "headed",
              "head", "directed", "director", "architected", "founded", "founder", "sole", "solely",
              "single-handedly", "all", "every", "always", "entire", "only", "expert", "senior",
              "principal", "staff", "chief", "best", "top", "first", "hundreds", "thousands",
              "millions", "billions", "dozens", "major", "massive", "world-class", "award-winning"}
CREDENTIALS = {"degree", "bachelor", "bachelors", "master", "masters", "phd", "doctorate", "mba",
               "certified", "certification", "certificate", "licensed", "license", "graduated",
               "graduate", "accredited", "chartered", "completed", "qualified"}
STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "as",
             "from", "into", "via", "using", "use", "used", "that", "this", "these", "those", "which",
             "who", "while", "across", "over", "within", "my", "our", "their", "its", "is", "are",
             "was", "were", "be", "been", "has", "have", "had", "also", "both"}
# Findings a candidate may knowingly accept at approval time. Every other finding blocks.
ACKNOWLEDGEABLE = {"new_content"}


def _numbers(text):
    return sorted(re.sub(r"\s+", "", m.group(0)).casefold().replace(",", "") for m in NUMBER.finditer(text))


def _words(text):
    return [w.strip("'-").casefold() for w in WORD.findall(text) if w.strip("'-")]


def _negation_count(text):
    return sum(1 for w in _words(text) if w in NEGATIONS) + text.casefold().count("n't")


def _named(text):
    """Capitalized tokens other than a sentence-initial word, plus mixed-case tokens and acronyms."""
    names = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        for position, token in enumerate(WORD.findall(sentence)):
            token = token.strip("'-")
            if token and (any(c.isupper() for c in token[1:]) or (position > 0 and token[0].isupper())):
                names.add(token.casefold())
    return names


def check(claim, paraphrase):
    """Return {"verdict": "exact"|"guard_pass"|"reject", "findings": [codes], "guard": version}."""
    if paraphrase == claim:
        return {"verdict": "exact", "findings": [], "guard": GUARD_VERSION}
    findings = []
    if not _words(paraphrase):
        findings.append("empty")
    if _numbers(paraphrase) != _numbers(claim):
        findings.append("quantity_changed")
    claim_words = set(_words(claim))
    if not _named(paraphrase) <= claim_words:
        findings.append("entity_added")
    if _negation_count(paraphrase) != _negation_count(claim):
        findings.append("negation_changed")
    added = set(_words(paraphrase)) - claim_words
    if added & ESCALATION:
        findings.append("scope_escalation")
    if added & CREDENTIALS:
        findings.append("credential_added")
    stems = {w[:5] for w in claim_words}
    if any(len(w) > 3 and w[:5] not in stems for w in added - STOPWORDS - ESCALATION - CREDENTIALS):
        findings.append("new_content")
    return {"verdict": "reject" if findings else "guard_pass", "findings": findings, "guard": GUARD_VERSION}
