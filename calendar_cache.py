#!/usr/bin/env python3
"""
Calendar Data Caching System for Church Calendar
Caches Google Calendar data at service start time for Raspberry Pi Zero 2W performance
"""

import json
import urllib.request
import urllib.error
import urllib.parse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
logger = logging.getLogger('church-calendar.calendar-cache')

# Load calendar configurations from config.json
def _load_calendars():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json'), 'r') as f:
            cfg = json.load(f)
            cals = cfg.get("calendars", [])
            if cals:
                return cals
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load calendars from config.json: {e}")
    logger.error("No calendars configured. Add a 'calendars' array to config.json (see config.example.json).")
    return []

CALENDARS = _load_calendars()

# Cache configuration
CACHE_CONFIG = {
    "cache_file": "calendar_cache.json",
    "cache_ttl_hours": 24,  # Cache for 24 hours
    "fetch_timeout": 15  # Timeout for calendar fetches
}

# Day name to weekday number (Monday=0 per Python's weekday())
BYDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

class CalendarCache:
    """Handles calendar data caching for Pi Zero 2W performance"""
    
    def __init__(self):
        self.config = CACHE_CONFIG
        self.cache_file = self.config["cache_file"]
        self.cache = self._load_cache()
    
    def _load_cache(self):
        """Load calendar cache from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    # Check if cache is still valid
                    if self._is_cache_valid(data):
                        logger.info(f"Loaded calendar cache from {self.cache_file}")
                        return data["events"]
                    else:
                        logger.info("Calendar cache expired, will fetch fresh data")
            except Exception as e:
                logger.warning(f"Failed to load calendar cache: {e}")
        return []
    
    def _save_cache(self, events):
        """Save calendar cache to file"""
        try:
            cache_data = {
                "events": events,
                "timestamp": datetime.now().isoformat(),
                "source": "Google Calendar API"
            }
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"Saved calendar cache to {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to save calendar cache: {e}")
    
    def _is_cache_valid(self, cache_data):
        """Check if cache is still valid based on TTL"""
        if "timestamp" not in cache_data:
            return False
        
        try:
            cache_time = datetime.fromisoformat(cache_data["timestamp"])
            age_hours = (datetime.now() - cache_time).total_seconds() / 3600
            return age_hours < self.config["cache_ttl_hours"]
        except Exception:
            return False
    
    def _get_pacific_offset(self, dt):
        """Return UTC offset for Pacific time (simplified: PDT Mar-Nov, PST otherwise)."""
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

    def _parse_ical_datetime(self, dtstr, param=""):
        """Parse an iCal datetime string into a Python datetime."""
        dtstr = dtstr.strip()
        
        # Check if it's an all-day event (VALUE=DATE in param or 8-char date)
        is_all_day = "VALUE=DATE" in param and "VALUE=DATE-TIME" not in param
        
        # Extract TZID if present
        tzid = None
        if "TZID=" in param:
            for part in param.split(";"):
                if part.startswith("TZID="):
                    tzid = part[5:].strip()
                    break
        
        # Handle TZID parameter in value (e.g., TZID=America/Los_Angeles:20260220T100000)
        if ":" in dtstr and not dtstr.startswith("2"):
            dtstr = dtstr.split(":")[-1]
        
        try:
            if len(dtstr) == 8:  # All-day event: 20260220
                return datetime.strptime(dtstr, "%Y%m%d"), True
            elif dtstr.endswith("Z"):  # UTC time
                return datetime.strptime(dtstr, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc), is_all_day
            else:  # Local time - apply timezone if known
                dt = datetime.strptime(dtstr, "%Y%m%dT%H%M%S")
                if tzid and tzid in {"America/Los_Angeles", "America/Vancouver", "America/Tijuana", "US/Pacific", "PST8PDT"}:
                    offset = self._get_pacific_offset(dt)
                    dt = dt.replace(tzinfo=timezone(offset))
                else:
                    # Treat as UTC if no timezone info
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, is_all_day
        except ValueError:
            return None, False

    def _unfold_ical(self, text):
        """Unfold iCal line continuations (lines starting with space or tab)."""
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        unfolded = []
        for line in lines:
            if line.startswith(' ') or line.startswith('\t'):
                if unfolded:
                    unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        return unfolded

    def _unescape_ical_text(self, text):
        """Unescape iCal text escapes: \\, \\; \\n \\N \\\\"""
        if not text:
            return text
        text = text.replace("\\,", ",")
        text = text.replace("\\;", ";")
        text = text.replace("\\n", " ").replace("\\N", " ")
        text = text.replace("\\\\", "\\")
        return text.strip()

    def _nth_weekday_of_month(self, year, month, weekday, n):
        """Return date for nth weekday in month (n can be negative for last occurrences)."""
        import calendar

        if n > 0:
            first_day = datetime(year, month, 1)
            days_ahead = weekday - first_day.weekday()
            if days_ahead < 0:
                days_ahead += 7
            first_occurrence = first_day + timedelta(days=days_ahead)
            result = first_occurrence + timedelta(weeks=n - 1)
            if result.month != month:
                return None
            return result

        if n < 0:
            last_day = datetime(year, month, calendar.monthrange(year, month)[1])
            days_behind = last_day.weekday() - weekday
            if days_behind < 0:
                days_behind += 7
            last_occurrence = last_day - timedelta(days=days_behind)
            result = last_occurrence + timedelta(weeks=n + 1)
            if result.month != month:
                return None
            return result

        return None

    def _parse_byday(self, byday_str):
        """Parse BYDAY strings like '4TU,-1MO' into list[(n, weekday)]."""
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

    def _expand_recurring_event(self, start_dt, end_dt, rrule, now, end_range, exdates=None):
        """Expand recurring iCal event occurrences within the target time window."""
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
                byday = self._parse_byday(value)

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
                    candidate_date = self._nth_weekday_of_month(year, month, weekday, n)
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

    def _parse_ical(self, ical_text, calendar_color, calendar_name):
        """Parse iCal text and extract events within the next 10 days, including recurring events."""
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_range = today_midnight + timedelta(days=10)

        lines = self._unfold_ical(ical_text)

        # First pass: collect all VEVENT blocks.
        raw_events = []
        events = []
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
                        param_part = line.split(":", 1)[0]
                        value = line.split(":", 1)[1].strip()
                        event["dtstart"] = value
                        event["dtstart_param"] = param_part
                elif line.startswith("DTEND"):
                    if ":" in line:
                        param_part = line.split(":", 1)[0]
                        value = line.split(":", 1)[1].strip()
                        event["dtend"] = value
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

        masters = {}
        overrides = {}
        singles = []
        for ev in raw_events:
            uid = ev.get("uid", "")
            if ev.get("rrule"):
                masters[uid] = ev
            elif ev.get("recurrence_id"):
                if uid not in overrides:
                    overrides[uid] = {}
                overrides[uid][ev["recurrence_id"]] = ev
            else:
                singles.append(ev)

        def make_evt_from(ev_data, s, e, all_day):
            return {
                "summary": self._unescape_ical_text(ev_data.get("summary", "")),
                "description": self._unescape_ical_text(ev_data.get("description", "")),
                "location": self._unescape_ical_text(ev_data.get("location", "")),
                "start": s.strftime("%Y-%m-%d") if all_day else s.isoformat(),
                "end": e.strftime("%Y-%m-%d") if all_day else e.isoformat(),
                "allDay": all_day,
                "color": calendar_color,
                "calendar": calendar_name,
            }

        for uid, ev in masters.items():
            dtstart = ev.get("dtstart", "")
            dtend = ev.get("dtend", "")
            rrule = ev.get("rrule", "")
            exdates = ev.get("exdates", set())
            uid_overrides = overrides.get(uid, {})
            all_exdates = exdates | set(uid_overrides.keys())

            start_dt, is_all_day = self._parse_ical_datetime(dtstart, ev.get("dtstart_param", ""))
            end_dt, _ = self._parse_ical_datetime(dtend, ev.get("dtend_param", "")) if dtend else (None, False)
            if start_dt is None:
                continue
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if end_dt is None:
                end_dt = start_dt + timedelta(hours=1)

            for occ_start, occ_end in self._expand_recurring_event(start_dt, end_dt, rrule, today_midnight, end_range, all_exdates):
                events.append(make_evt_from(ev, occ_start, occ_end, is_all_day))

            for _, override_ev in uid_overrides.items():
                ov_start, ov_all_day = self._parse_ical_datetime(override_ev.get("dtstart", ""), override_ev.get("dtstart_param", ""))
                ov_end, _ = self._parse_ical_datetime(override_ev.get("dtend", ""), override_ev.get("dtend_param", "")) if override_ev.get("dtend") else (None, False)
                if ov_start is None:
                    continue
                if ov_start.tzinfo is None:
                    ov_start = ov_start.replace(tzinfo=timezone.utc)
                if ov_end and ov_end.tzinfo is None:
                    ov_end = ov_end.replace(tzinfo=timezone.utc)
                if ov_end is None:
                    ov_end = ov_start + timedelta(hours=1)
                if ov_end >= now and ov_start <= end_range:
                    events.append(make_evt_from(override_ev, ov_start, ov_end, ov_all_day))

        for ev in singles:
            start_dt, is_all_day = self._parse_ical_datetime(ev.get("dtstart", ""), ev.get("dtstart_param", ""))
            end_dt, _ = self._parse_ical_datetime(ev.get("dtend", ""), ev.get("dtend_param", "")) if ev.get("dtend") else (None, False)
            if start_dt is None:
                continue
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if end_dt is None:
                end_dt = start_dt + timedelta(hours=1)

            if is_all_day and end_dt and (end_dt - start_dt).days > 1:
                span_end = end_dt - timedelta(days=1)
                current_day = start_dt
                while current_day <= span_end:
                    current_day_aware = current_day if current_day.tzinfo is not None else current_day.replace(tzinfo=timezone.utc)
                    if current_day_aware >= today_midnight and current_day_aware <= end_range:
                        events.append(make_evt_from(ev, current_day, current_day + timedelta(days=1), True))
                    current_day = current_day + timedelta(days=1)
            else:
                if start_dt >= today_midnight and start_dt <= end_range:
                    events.append(make_evt_from(ev, start_dt, end_dt, is_all_day))

        return events

    def _get_calendar_name_from_ical(self, ical_text):
        """Extract calendar name from iCal X-WR-CALNAME property."""
        lines = self._unfold_ical(ical_text)
        for line in lines:
            if line.startswith("X-WR-CALNAME:"):
                return line[13:].strip()
        return "Calendar"

    def fetch_calendar_events(self):
        """Fetch events from all configured Google Calendars."""
        if self.cache:
            logger.info(f"Using cached calendar data ({len(self.cache)} events)")
            return self.cache
        
        logger.info("Fetching calendar events from Google Calendar...")
        all_events = []
        
        for cal in CALENDARS:
            cal_id = cal["id"]
            color = cal["color"]
            url = f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(cal_id, safe='@')}/public/basic.ics"
            
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ChurchCalendar/1.0)"
                })
                with urllib.request.urlopen(req, timeout=self.config["fetch_timeout"]) as response:
                    ical_text = response.read().decode("utf-8", errors="replace")
                    cal_name = self._get_calendar_name_from_ical(ical_text)
                    cal_events = self._parse_ical(ical_text, color, cal_name)
                    all_events.extend(cal_events)
                    logger.info(f"  ✓ {cal_name}: {len(cal_events)} events")
            except Exception as e:
                logger.error(f"  ✗ Error fetching {cal_id}: {e}")
        
        # Sort by start time
        all_events.sort(key=lambda e: e["start"])

        # Keep fresh results in memory so repeated API reads avoid network fetches.
        self.cache = all_events
        
        # Cache the results
        self._save_cache(all_events)
        
        logger.info(f"Total: {len(all_events)} events in the next 10 days")
        return all_events


def main():
    """Test the calendar cache system"""
    cache = CalendarCache()
    events = cache.fetch_calendar_events()

    logger.info(f"calendar_cache_summary events={len(events)} cache_file={cache.cache_file} calendar_sources={len(CALENDARS)}")

    # Show sample events
    for i, event in enumerate(events[:5]):
        logger.info(f"calendar_cache_sample index={i} start={event['start']} summary={event['summary']} calendar={event['calendar']}")


if __name__ == "__main__":
    main()