#!/usr/bin/env python3
"""
Shared iCal parsing utilities for the Church Calendar system.

Used by both server.py and calendar_cache.py to eliminate duplicated parsing
logic. Consolidating here reduces the risk of the two copies drifting apart.
"""

import calendar as _calendar
from datetime import datetime, timedelta, timezone

# Pacific time zone identifiers recognised by the parser
PACIFIC_TZIDS = {
    "America/Los_Angeles", "America/Vancouver", "America/Tijuana",
    "US/Pacific", "PST8PDT"
}

# Day-name → Python weekday number (Monday = 0)
BYDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def get_pacific_offset(dt):
    """Return UTC offset for Pacific time (PDT Mar–Nov, PST otherwise)."""
    year = dt.year
    # 2nd Sunday in March
    march1 = datetime(year, 3, 1)
    dst_start = march1 + timedelta(days=(6 - march1.weekday()) % 7 + 7)
    # 1st Sunday in November
    nov1 = datetime(year, 11, 1)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    if dst_start <= dt < dst_end:
        return timedelta(hours=-7)  # PDT
    return timedelta(hours=-8)  # PST


def parse_ical_datetime(dtstr, param=""):
    """Parse an iCal datetime string into a (datetime, is_all_day) tuple.

    *param* is the property parameter segment before the colon, e.g.
    ``'DTSTART;VALUE=DATE'`` or ``'DTSTART;TZID=America/Los_Angeles'``.
    Returns ``(None, False)`` on parse failure.
    """
    dtstr = dtstr.strip()
    is_all_day = "VALUE=DATE" in param and "VALUE=DATE-TIME" not in param

    tzid = None
    if "TZID=" in param:
        for part in param.split(";"):
            if part.startswith("TZID="):
                tzid = part[5:].strip()
                break

    # Strip any leading "TZID=…:" prefix embedded in the value
    if ":" in dtstr and not dtstr.startswith("2"):
        dtstr = dtstr.split(":")[-1]

    try:
        if len(dtstr) == 8:  # All-day: 20260220
            return datetime.strptime(dtstr, "%Y%m%d"), True
        elif dtstr.endswith("Z"):  # UTC
            return datetime.strptime(dtstr, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), is_all_day
        else:  # Local time – apply timezone when known
            dt = datetime.strptime(dtstr, "%Y%m%dT%H%M%S")
            if tzid and tzid in PACIFIC_TZIDS:
                dt = dt.replace(tzinfo=timezone(get_pacific_offset(dt)))
            else:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, is_all_day
    except ValueError:
        return None, False


def unfold_ical(text):
    """Unfold iCal line continuations (lines starting with a space or tab)."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    unfolded = []
    for line in lines:
        if line.startswith(' ') or line.startswith('\t'):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def unescape_ical_text(text):
    r"""Unescape iCal text: \, \; \n \N \\"""
    if not text:
        return text
    text = text.replace("\\,", ",")
    text = text.replace("\\;", ";")
    text = text.replace("\\n", " ").replace("\\N", " ")
    text = text.replace("\\\\", "\\")
    return text.strip()


def nth_weekday_of_month(year, month, weekday, n):
    """Return the date of the *n*-th occurrence of *weekday* in the given month.

    *n* = 1 → first, *n* = 2 → second, *n* = -1 → last, etc.
    *weekday*: 0 = Monday … 6 = Sunday (Python convention).
    Returns ``None`` when the requested occurrence does not exist.
    """
    if n > 0:
        first_day = datetime(year, month, 1)
        days_ahead = weekday - first_day.weekday()
        if days_ahead < 0:
            days_ahead += 7
        result = first_day + timedelta(days=days_ahead) + timedelta(weeks=n - 1)
        if result.month != month:
            return None
        return result
    if n < 0:
        last_day = datetime(year, month, _calendar.monthrange(year, month)[1])
        days_behind = last_day.weekday() - weekday
        if days_behind < 0:
            days_behind += 7
        result = last_day - timedelta(days=days_behind) + timedelta(weeks=n + 1)
        if result.month != month:
            return None
        return result
    return None


def parse_byday(byday_str):
    """Parse a BYDAY value like ``'4TU'``, ``'-1MO'``, ``'TU,TH'``.

    Returns a list of ``(n, weekday)`` tuples where *n* = 0 means "every
    occurrence of this weekday".
    """
    result = []
    for part in byday_str.split(","):
        part = part.strip()
        if len(part) < 2:
            continue
        day_code = part[-2:].upper()
        prefix = part[:-2]
        weekday = BYDAY_MAP.get(day_code)
        if weekday is None:
            continue
        n = int(prefix) if prefix else 0
        result.append((n, weekday))
    return result


def expand_recurring_event(start_dt, end_dt, rrule, now, end_range, exdates=None):
    """Expand a recurring iCal event into occurrences within [now-1d, end_range].

    Supports FREQ=DAILY/WEEKLY/MONTHLY/YEARLY with BYDAY, INTERVAL, COUNT,
    and UNTIL.  EXDATE exclusions are honoured.

    Returns a list of ``(occurrence_start, occurrence_end)`` tuples.
    """
    occurrences = []
    exdates = exdates or set()

    freq = "DAILY"
    interval = 1
    count = None
    until = None
    byday = []

    for part in rrule.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key == "FREQ":
            freq = value.upper()
        elif key == "INTERVAL":
            try:
                interval = int(value)
            except Exception:
                interval = 1
        elif key == "COUNT":
            try:
                count = int(value)
            except Exception:
                count = None
        elif key == "UNTIL":
            try:
                until = datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
            except Exception:
                until = None
        elif key == "BYDAY":
            byday = parse_byday(value)

    duration = end_dt - start_dt if end_dt else timedelta(hours=1)

    if freq == "MONTHLY" and byday:
        year = start_dt.year
        month = start_dt.month
        occ_count = 0
        months_checked = 0
        while months_checked < 200:
            for n, weekday in byday:
                if n == 0:
                    continue
                candidate_date = nth_weekday_of_month(year, month, weekday, n)
                if candidate_date is None:
                    continue
                candidate = candidate_date.replace(
                    hour=start_dt.hour,
                    minute=start_dt.minute,
                    second=start_dt.second,
                    tzinfo=start_dt.tzinfo,
                )
                if candidate < start_dt:
                    continue
                if until and candidate > until:
                    return occurrences
                if candidate.strftime("%Y%m%d") in exdates:
                    occ_count += 1
                    if count and occ_count >= count:
                        return occurrences
                    continue
                if candidate >= now - timedelta(days=1) and candidate <= end_range:
                    occurrences.append((candidate, candidate + duration))
                occ_count += 1
                if count and occ_count >= count:
                    return occurrences
                if candidate > end_range:
                    return occurrences
            month += interval
            while month > 12:
                month -= 12
                year += 1
            months_checked += 1
        return occurrences

    if freq == "WEEKLY" and byday:
        current = start_dt
        occ_count = 0
        while current <= end_range and occ_count < 500:
            for _, weekday in byday:
                days_ahead = weekday - current.weekday()
                candidate = current + timedelta(days=days_ahead)
                if candidate < start_dt:
                    continue
                if until and candidate > until:
                    return occurrences
                if candidate.strftime("%Y%m%d") in exdates:
                    continue
                if candidate >= now - timedelta(days=1) and candidate <= end_range:
                    occurrences.append((candidate, candidate + duration))
                occ_count += 1
                if count and occ_count >= count:
                    return occurrences
            current = current + timedelta(weeks=interval)
        return occurrences

    # DAILY, WEEKLY (no BYDAY), MONTHLY (no BYDAY), YEARLY
    current = start_dt
    occ_count = 0
    while current <= end_range and occ_count < 200:
        if current.strftime("%Y%m%d") not in exdates and current >= now - timedelta(days=1):
            occurrences.append((current, current + duration))

        if freq == "DAILY":
            current = current + timedelta(days=interval)
        elif freq == "WEEKLY":
            current = current + timedelta(weeks=interval)
        elif freq == "MONTHLY":
            try:
                month = current.month + interval
                year = current.year
                while month > 12:
                    month -= 12
                    year += 1
                current = current.replace(month=month, year=year)
            except ValueError:
                current = current + timedelta(weeks=4)
        elif freq == "YEARLY":
            try:
                current = current.replace(year=current.year + interval)
            except ValueError:
                current = current.replace(year=current.year + interval, day=28)
        else:
            break

        occ_count += 1
        if count and occ_count >= count:
            break
        if until and current > until:
            break

    return occurrences


def get_calendar_name_from_ical(ical_text):
    """Extract the calendar display name from the X-WR-CALNAME property."""
    for line in unfold_ical(ical_text):
        if line.startswith("X-WR-CALNAME:"):
            return line[13:].strip()
    return "Calendar"


def parse_ical(ical_text, calendar_color, calendar_name):
    """Parse iCal text and return events within the next 10 days.

    Two-pass approach:
    1. Collect all VEVENT blocks (master recurring events and RECURRENCE-ID
       overrides).
    2. Expand master events using the shared ``expand_recurring_event`` helper,
       substituting overrides for specific occurrences.
    """
    now = datetime.now(timezone.utc)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_range = today_midnight + timedelta(days=10)

    lines = unfold_ical(ical_text)

    # --- First pass: collect raw VEVENT blocks ---
    raw_events = []
    in_event = False
    event = {}

    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            in_event = True
            event = {}
        elif line.strip() == "END:VEVENT":
            in_event = False
            if event.get("summary") or event.get("dtstart"):
                raw_events.append(dict(event))
            event = {}
        elif in_event:
            if line.startswith("SUMMARY:"):
                event["summary"] = line[8:].strip()
            elif line.startswith("DESCRIPTION:"):
                event["description"] = line[12:].strip()
            elif line.startswith("LOCATION:"):
                event["location"] = line[9:].strip()
            elif line.startswith("DTSTART"):
                if ":" in line:
                    param_part, value = line.split(":", 1)
                    event["dtstart"] = value.strip()
                    event["dtstart_param"] = param_part
            elif line.startswith("DTEND"):
                if ":" in line:
                    param_part, value = line.split(":", 1)
                    event["dtend"] = value.strip()
                    event["dtend_param"] = param_part
            elif line.startswith("RRULE:"):
                event["rrule"] = line[6:].strip()
            elif line.startswith("EXDATE"):
                if ":" in line:
                    exdate_val = line.split(":", 1)[1].strip()
                    for ex in exdate_val.split(","):
                        date_part = ex.strip()[:8]
                        if "exdates" not in event:
                            event["exdates"] = set()
                        event["exdates"].add(date_part)
            elif line.startswith("RECURRENCE-ID"):
                if ":" in line:
                    event["recurrence_id"] = line.split(":", 1)[1].strip()[:8]
            elif line.startswith("UID:"):
                event["uid"] = line[4:].strip()

    # --- Separate masters, overrides, and single events ---
    masters = {}   # uid → event dict (has RRULE)
    overrides = {} # uid → {date_str → event dict} (has RECURRENCE-ID)
    singles = []   # events without RRULE or RECURRENCE-ID

    for ev in raw_events:
        uid = ev.get("uid", "")
        if ev.get("rrule"):
            masters[uid] = ev
        elif ev.get("recurrence_id"):
            overrides.setdefault(uid, {})[ev["recurrence_id"]] = ev
        else:
            singles.append(ev)

    events = []

    def make_evt_from(ev_data, s, e, all_day):
        return {
            "summary": unescape_ical_text(ev_data.get("summary", "")),
            "description": unescape_ical_text(ev_data.get("description", "")),
            "location": unescape_ical_text(ev_data.get("location", "")),
            "start": s.strftime("%Y-%m-%d") if all_day else s.isoformat(),
            "end": e.strftime("%Y-%m-%d") if all_day else e.isoformat(),
            "allDay": all_day,
            "color": calendar_color,
            "calendar": calendar_name,
        }

    def _ensure_tz(dt):
        return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt

    # --- Process master recurring events ---
    for uid, ev in masters.items():
        uid_overrides = overrides.get(uid, {})
        all_exdates = ev.get("exdates", set()) | set(uid_overrides.keys())

        start_dt, is_all_day = parse_ical_datetime(ev.get("dtstart", ""), ev.get("dtstart_param", ""))
        end_dt, _ = parse_ical_datetime(ev.get("dtend", ""), ev.get("dtend_param", "")) if ev.get("dtend") else (None, False)

        if start_dt is None:
            continue
        start_dt = _ensure_tz(start_dt)
        end_dt = _ensure_tz(end_dt) or start_dt + timedelta(hours=1)

        for occ_start, occ_end in expand_recurring_event(
            start_dt, end_dt, ev.get("rrule", ""), today_midnight, end_range, all_exdates
        ):
            events.append(make_evt_from(ev, occ_start, occ_end, is_all_day))

        # Add override occurrences that fall within the window
        for override_ev in uid_overrides.values():
            ov_start, ov_all_day = parse_ical_datetime(override_ev.get("dtstart", ""), override_ev.get("dtstart_param", ""))
            ov_end, _ = parse_ical_datetime(override_ev.get("dtend", ""), override_ev.get("dtend_param", "")) if override_ev.get("dtend") else (None, False)
            if ov_start is None:
                continue
            ov_start = _ensure_tz(ov_start)
            ov_end = _ensure_tz(ov_end) or ov_start + timedelta(hours=1)
            if ov_end >= now and ov_start <= end_range:
                events.append(make_evt_from(override_ev, ov_start, ov_end, ov_all_day))

    # --- Process single (non-recurring) events ---
    for ev in singles:
        start_dt, is_all_day = parse_ical_datetime(ev.get("dtstart", ""), ev.get("dtstart_param", ""))
        end_dt, _ = parse_ical_datetime(ev.get("dtend", ""), ev.get("dtend_param", "")) if ev.get("dtend") else (None, False)
        if start_dt is None:
            continue
        start_dt = _ensure_tz(start_dt)
        end_dt = _ensure_tz(end_dt) or start_dt + timedelta(hours=1)

        if is_all_day and (end_dt - start_dt).days > 1:
            # Multi-day all-day event: emit one entry per day
            span_end = end_dt - timedelta(days=1)
            current_day = start_dt
            while current_day <= span_end:
                current_day_aware = _ensure_tz(current_day)
                if today_midnight <= current_day_aware <= end_range:
                    events.append(make_evt_from(ev, current_day, current_day + timedelta(days=1), True))
                current_day = current_day + timedelta(days=1)
        else:
            if today_midnight <= start_dt <= end_range:
                events.append(make_evt_from(ev, start_dt, end_dt, is_all_day))

    return events
