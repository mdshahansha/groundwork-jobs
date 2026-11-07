"""JW-23: sending schedule, daily caps in the candidate's time zone, DST, partial dates (FR-AUT-06).

- Each channel has a daily cap from policy, never above the hard cap in code, and allowed local
  hours. A "day" is the candidate's local calendar day in their IANA zone, so a cap resets at
  local midnight, including on 23- and 25-hour DST days.
- Caps count accepted, in-flight and unknown attempts (conservative: an unknown may have sent).
- Outside the window, or with the cap reached, an action waits: `next_slot` returns the next
  allowed UTC instant. A window start that falls in a DST gap moves to the first valid minute
  after it; an ambiguous one (fall back) takes the first occurrence.
- Partial dates ("2026", "2026-09") keep their precision instead of inventing a day.
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import instant, require, utcnow

HARD_CAPS = {"email": 25, "comment": 15, "ats": 20}
COUNTED = ("accepted", "in_flight", "unknown")


def validate(policy):
    require(isinstance(policy, dict) and set(policy) == {"timezone", "channels"}, "invalid_schema",
            "Schedule needs timezone and channels.")
    try:
        ZoneInfo(policy["timezone"])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        require(False, "invalid_schema", "Unknown IANA time zone.")
    channels = policy["channels"]
    require(isinstance(channels, dict) and channels and set(channels) <= set(HARD_CAPS), "invalid_schema",
            "Channels are email, comment or ats.")
    for name, rule in channels.items():
        require(isinstance(rule, dict) and set(rule) == {"daily_cap", "hours"}, "invalid_schema",
                "Each channel needs daily_cap and hours.")
        cap, hours = rule["daily_cap"], rule["hours"]
        require(type(cap) is int and 0 <= cap <= HARD_CAPS[name], "cap_above_hard_limit",
                f"{name} daily cap must be 0..{HARD_CAPS[name]}.")
        require(isinstance(hours, list) and len(hours) == 2 and all(type(h) is int for h in hours) and
                0 <= hours[0] < hours[1] <= 24, "invalid_schema", "hours is [start, end) in local whole hours.")
    return policy


def _local_start(zone, day, hour):
    """First real local instant at or after `day hour:00` (skips a DST gap; first fold if ambiguous)."""
    if hour == 24:
        day, hour = day + timedelta(days=1), 0
    naive = datetime.combine(day, time(hour))
    for minutes in range(0, 180):
        candidate = (naive + timedelta(minutes=minutes)).replace(tzinfo=zone, fold=0)
        # A nonexistent wall time does not survive a UTC round trip.
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == candidate.replace(tzinfo=None):
            return candidate.astimezone(timezone.utc)
    raise AssertionError("no valid local time within three hours")


class Schedule:
    def __init__(self, workspace):
        self.ws = workspace
        self.db = workspace.db

    def set_policy(self, policy):
        policy = validate(policy)
        with self.ws.store.transaction():
            self.db.execute("INSERT INTO controls VALUES ('schedule',?) ON CONFLICT(name) DO UPDATE SET "
                            "value=excluded.value", (json.dumps(policy, sort_keys=True),))
            self.ws.store.audit("schedule_set", "controls")
        return policy

    def policy(self):
        row = self.db.execute("SELECT value FROM controls WHERE name='schedule'").fetchone()
        return json.loads(row["value"]) if row else None

    def _day_bounds(self, zone, local_day):
        return _local_start(zone, local_day, 0), _local_start(zone, local_day + timedelta(days=1), 0)

    def used(self, channel, at=None):
        policy = self.policy()
        zone = ZoneInfo(policy["timezone"])
        now = instant(at or utcnow())
        start, end = self._day_bounds(zone, now.astimezone(zone).date())
        rows = self.db.execute("SELECT created_at FROM attempts WHERE channel=? AND state IN (?,?,?)",
                               (channel, *COUNTED)).fetchall()
        return sum(1 for r in rows if start <= instant(r["created_at"]) < end)

    def check(self, channel, at=None):
        """None when the channel may act now; otherwise (code, message, next allowed UTC instant)."""
        policy = self.policy()
        if policy is None or channel not in policy["channels"]:
            return None
        now = instant(at or utcnow())
        rule = policy["channels"][channel]
        zone = ZoneInfo(policy["timezone"])
        local = now.astimezone(zone)
        if self.used(channel, now.isoformat()) >= rule["daily_cap"]:
            return ("daily_cap_reached", "Daily cap reached; the action waits.",
                    self.next_slot(channel, now.isoformat(), skip_today=True))
        open_, close = (_local_start(zone, local.date(), h) for h in rule["hours"])
        if not open_ <= now < close:
            return ("outside_allowed_hours", "Outside allowed hours; the action waits.",
                    self.next_slot(channel, now.isoformat()))
        return None

    def next_slot(self, channel, at=None, skip_today=False):
        policy = self.policy()
        require(policy is not None and channel in policy["channels"], "not_found", "No schedule for channel.")
        rule = policy["channels"][channel]
        require(rule["daily_cap"] > 0, "channel_capped_off", "Daily cap is 0; this channel never sends.")
        zone = ZoneInfo(policy["timezone"])
        now = instant(at or utcnow())
        day = now.astimezone(zone).date()
        for offset in range(1 if skip_today else 0, 8):
            local_day = day + timedelta(days=offset)
            open_ = _local_start(zone, local_day, rule["hours"][0])
            close = _local_start(zone, local_day, rule["hours"][1])
            slot = max(open_, now) if offset == 0 else open_
            if slot < close:
                return slot.isoformat()
        raise AssertionError("no slot within a week")


PARTIAL = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def partial_date(value):
    """'2026' -> year, '2026-09' -> month, '2026-09-04' -> day; range covers what the text claims."""
    match = PARTIAL.match(value.strip()) if isinstance(value, str) else None
    require(match is not None, "invalid_date", "Use YYYY, YYYY-MM or YYYY-MM-DD.")
    year, month, day = (int(g) if g else None for g in match.groups())
    try:
        if day:
            start = end = date(year, month, day)
            precision, label = "day", f"{start.day} {start:%b %Y}"
        elif month:
            start, end = date(year, month, 1), date(year, month, monthrange(year, month)[1])
            precision, label = "month", start.strftime("%b %Y")
        else:
            start, end = date(year, 1, 1), date(year, 12, 31)
            precision, label = "year", str(year)
    except ValueError:
        require(False, "invalid_date", "Date does not exist.")
    return {"value": value.strip(), "precision": precision, "start": start.isoformat(), "end": end.isoformat(),
            "display": label}
