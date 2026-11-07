"""JW-19: metric dictionary, cohorts and activity time (FR-ANL-01).

Every metric declares its numerator, denominator, unit and what makes it unknown. A metric with
a zero denominator, or whose inputs are not measured here, is `unknown` with the reason, never 0.
Rates are reported with their counts so a reader can see how little data sits behind them.
Cohorts group jobs by the ISO week of their first preparation task. No causal claims are made.
"""

from datetime import datetime, timedelta

from .contracts import instant, require, string, utcnow

IDLE_SECONDS = 300
EVENTS = ("open", "review", "edit", "approve", "close")

# name: (definition, numerator SQL, denominator SQL, unit). Both SQL take the job-id list.
DICTIONARY = {
    "drafts_completed": ("Draft tasks completed / draft tasks created",
                         "SELECT count(*) FROM tasks WHERE kind IN ('draft_cv','draft_letter') AND state='completed' "
                         "AND job_id IN ({ids})",
                         "SELECT count(*) FROM tasks WHERE kind IN ('draft_cv','draft_letter') AND job_id IN ({ids})",
                         "ratio"),
    "mechanical_pass": ("Verifications that passed gates 1-2 / verifications run",
                        "SELECT count(*) FROM verifications v JOIN tasks t ON t.id=v.task_id WHERE "
                        "v.status='mechanical_passed' AND t.job_id IN ({ids})",
                        "SELECT count(*) FROM verifications v JOIN tasks t ON t.id=v.task_id WHERE "
                        "v.status<>'erased' AND t.job_id IN ({ids})", "ratio"),
    "email_unknown": ("E-mail attempts still unknown / e-mail attempts",
                      "SELECT count(*) FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id JOIN "
                      "action_envelopes e ON e.id=z.envelope_id WHERE a.channel='email' AND a.state='unknown' "
                      "AND e.job_id IN ({ids})",
                      "SELECT count(*) FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id JOIN "
                      "action_envelopes e ON e.id=z.envelope_id WHERE a.channel='email' AND e.job_id IN ({ids})",
                      "ratio"),
    "reply_rate": ("Jobs with a matched recruiter reply / jobs with an accepted e-mail",
                   "SELECT count(DISTINCT job_id) FROM mail_events WHERE state='attached' AND classification NOT IN "
                   "('auto_reply','bounce','other') AND job_id IN ({ids})",
                   "SELECT count(DISTINCT e.job_id) FROM attempts a JOIN authorisations z ON z.id=a.authorisation_id "
                   "JOIN action_envelopes e ON e.id=z.envelope_id WHERE a.channel='email' AND a.state='accepted' "
                   "AND e.job_id IN ({ids})", "ratio"),
    "bounce_rate": ("Bounces matched to a job / jobs with an accepted e-mail",
                    "SELECT count(DISTINCT job_id) FROM mail_events WHERE classification='bounce' AND job_id IN ({ids})",
                    None, "ratio"),
    "manual_applications": ("Jobs with a manual_applied outcome / jobs in cohort",
                            "SELECT count(DISTINCT job_id) FROM outcomes WHERE kind='manual_applied' AND job_id IN ({ids})",
                            "SELECT count(*) FROM jobs WHERE id IN ({ids})", "ratio"),
}
UNMEASURED = {
    "cost": "Host-mediated model calls are not billed through this process.",
    "time_to_ready": "No document reaches `ready`: visual review of page images is not run.",
    "time_to_submitted": "No ATS adapter exists, so `submitted` has no evidence.",
}


def record_activity(ws, job_id, event, run_id=None, at=None):
    require(event in EVENTS, "invalid_schema", "Event is open, review, edit, approve or close.")
    ws.store.one("jobs", job_id)
    if run_id is not None:
        string(run_id, 100)
    when = instant(at or utcnow()).isoformat()
    with ws.store.transaction():
        ws.db.execute("INSERT INTO activity(job_id,run_id,event,at) VALUES (?,?,?,?)", (job_id, run_id, event, when))
    return {"job_id": job_id, "event": event, "at": when}


def active_time(ws, job_id, idle_seconds=IDLE_SECONDS):
    """Elapsed from first to last event; active sums gaps up to `idle_seconds`. Longer gaps are idle."""
    times = [instant(r["at"]) for r in ws.db.execute("SELECT at FROM activity WHERE job_id=? ORDER BY at", (job_id,))]
    if len(times) < 2:
        return {"job_id": job_id, "elapsed_seconds": None, "active_seconds": None, "idle_gaps": 0,
                "status": "unknown", "reason": "Fewer than two activity events."}
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    idle = [g for g in gaps if g > idle_seconds]
    return {"job_id": job_id, "elapsed_seconds": (times[-1] - times[0]).total_seconds(),
            "active_seconds": sum(g for g in gaps if g <= idle_seconds), "idle_gaps": len(idle),
            "idle_seconds_excluded": sum(idle), "idle_threshold_seconds": idle_seconds, "status": "measured"}


def cohorts(ws):
    """ISO week of each job's first draft task; jobs never prepared are in cohort `unprepared`."""
    groups = {}
    for row in ws.db.execute("SELECT j.id, min(t.created_at) AS first FROM jobs j LEFT JOIN tasks t ON t.job_id=j.id "
                             "AND t.kind IN ('draft_cv','draft_letter') GROUP BY j.id ORDER BY j.id"):
        if row["first"]:
            year, week, _ = instant(row["first"]).isocalendar()
            name = f"{year}-W{week:02d}"
        else:
            name = "unprepared"
        groups.setdefault(name, []).append(row["id"])
    return groups


def _value(ws, name, ids):
    definition, numerator, denominator, unit = DICTIONARY[name]
    if denominator is None:
        denominator = DICTIONARY["reply_rate"][2]
    marks = ",".join("?" * len(ids))
    num = ws.db.execute(numerator.format(ids=marks), ids).fetchone()[0]
    den = ws.db.execute(denominator.format(ids=marks), ids).fetchone()[0]
    if den == 0:
        return {"metric": name, "value": None, "status": "unknown", "numerator": num, "denominator": 0,
                "reason": "Zero denominator.", "unit": unit}
    return {"metric": name, "value": round(num / den, 4), "status": "measured", "numerator": num,
            "denominator": den, "unit": unit}


def report(ws):
    result = {"dictionary": {k: {"definition": v[0], "unit": v[3]} for k, v in DICTIONARY.items()},
              "unmeasured": UNMEASURED, "cohorts": {}}
    for name, ids in sorted(cohorts(ws).items()):
        result["cohorts"][name] = {"jobs": len(ids), "metrics": {m: _value(ws, m, ids) for m in DICTIONARY}}
    return result
