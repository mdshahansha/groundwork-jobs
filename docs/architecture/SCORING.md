# Deterministic ranking contract: calculations@1

This is the technical completion of previously unspecified arithmetic, not
product-approved calibration. PRD weights remain 35/15/10/10/10/10/5/5. The CLI
will accept explicit candidate assessments; no model or keyword extractor is
trusted to infer hard eligibility. Semantic mapping and calibration remain open.

All arithmetic uses Decimal, rounds once to two decimals with ROUND_HALF_UP,
and stays within 0..100. Score is relevance, not hiring probability or ATS score.
Confidence is the weighted fraction of known component inputs, not probability.
Ties use ascending immutable job ID. Unknowns alone never hard-exclude.

| Component | Formula |
|---|---|
| Required/preferred skills | Mean of supported=1, partial=0.5, unsupported=0, unknown=0.25; empty list=0.5 with zero confidence |
| Title/seniority | Alias mismatch=0; alias match with distance 0/1/2+=1/0.5/0; incomplete input=0.5, unknown |
| Domain | supported=1, partial=0.5, unsupported=0, unknown=0.5 |
| Location | exact=1, relocation=0.6, unclear=0.5, mismatch=0; explicit ineligible always excludes |
| Salary | Comparable ranges: intersection width divided by candidate range width, clipped to 0..1; point expectation scores 1 if inside job range; incomparable=0.5, unknown |
| Freshness | max(0, 1-age_days/window_days); absent or future date=0.5, unknown |
| Contact | official=1, named_recruiter=0.6, other=0.3, unknown=0.5 |

Salary comparison requires equal currency and pay basis (base, ctc or total).
No currency conversion or basis equivalence is assumed. Monthly pay multiplies
by 12; annual pay is unchanged. Hourly pay requires explicit hours/week, then
multiplies by hours/week and 52. Unknown hourly hours means incomparable.
Amounts must be finite, nonnegative, ordered, at most one billion, and have
numeric exponents within -12..12. Calculations use a private 28-digit Decimal
context, unaffected by the caller's ambient settings. These calculations
do not establish salary eligibility or promise an offer.

Experience counts the union of half-open intervals, never overlapping days twice.
Exact dates denote boundaries. For month-only dates the conservative start is
that month's last day and the conservative end is its first day. Open end means
the explicitly supplied calculation date. Clip at that date, count nonnegative
days, and divide by 365.25 with rounding down to two decimals. Min/max experience
is reported separately as below/within/above/unknown; it is not a ninth weighted
component and does not silently exclude a candidate.

The first `rank` command uses only the job's stored required requirements. Each
mapping has its zero-based requirement index, state and claim ID (null for unknown
or unsupported). Supported mappings require a whole-phrase occurrence in a current
public claim. This is conservative lexical validation, not semantic entailment.
Partial mappings retain their related-evidence label and never become supported.
The other components are explicitly supplied candidate assessments, not verified
facts. The result retains unassessed credibility and recommendation=review unless
an explicit hard location exclusion yields skip. There is no automatic preparation
or outreach. Every call reads current evidence; there is no stale ranking cache.
