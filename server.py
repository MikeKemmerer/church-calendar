#!/usr/bin/env python3
"""
St. Demetrios Greek Orthodox Church - Calendar Display Server
Optimized for Raspberry Pi Zero 2W performance with caching and image optimization.
Run: python server.py
Then open: http://localhost:8000
"""

import http.server
import json
import mimetypes
import urllib.request
import urllib.error
import urllib.parse
import os
import sys
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

mimetypes.add_type('font/woff2', '.woff2')

logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("church-calendar.server")

# Import optimization systems
try:
    from image_optimizer import ImageOptimizer
    from calendar_cache import CalendarCache
    IMAGE_OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    IMAGE_OPTIMIZATION_AVAILABLE = False
    logger.warning(f"Optimization modules not found: {e}")

# Import the multi-source image fetching system
try:
    from image_sources import ImageSourceManager
    IMAGE_SOURCES_AVAILABLE = True
except ImportError:
    IMAGE_SOURCES_AVAILABLE = False
    logger.warning("image_sources.py not found. Image functionality disabled.")

PORT = 8000
CALENDAR_CACHE_INSTANCE = None
LAST_LOGGED_RESTART_TRIGGER = object()

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


# Pacific timezone offset (PST = UTC-8, PDT = UTC-7)
# We use a simple fixed offset for Pacific time
PACIFIC_TZIDS = {
    "America/Los_Angeles", "America/Vancouver", "America/Tijuana",
    "US/Pacific", "PST8PDT"
}

def get_pacific_offset(dt):
    """Return UTC offset for Pacific time (simplified: PDT Mar-Nov, PST otherwise)."""
    # DST starts 2nd Sunday in March, ends 1st Sunday in November
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
    """Parse an iCal datetime string into a Python datetime.
    param is the part before the colon (e.g., 'DTSTART;VALUE=DATE' or 'DTSTART;TZID=America/Los_Angeles')
    """
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
            if tzid and tzid in PACIFIC_TZIDS:
                offset = get_pacific_offset(dt)
                dt = dt.replace(tzinfo=timezone(offset))
            else:
                # Treat as UTC if no timezone info
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, is_all_day
    except ValueError:
        return None, False


def unfold_ical(text):
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


# Day name to weekday number (Monday=0 per Python's weekday())
BYDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def nth_weekday_of_month(year, month, weekday, n):
    """Return the date of the nth occurrence of weekday in the given month.
    n=1 means first, n=2 means second, n=-1 means last, etc.
    weekday: 0=Monday, 6=Sunday (Python convention)
    """
    import calendar
    if n > 0:
        # Find first occurrence of weekday in month
        first_day = datetime(year, month, 1)
        days_ahead = weekday - first_day.weekday()
        if days_ahead < 0:
            days_ahead += 7
        first_occurrence = first_day + timedelta(days=days_ahead)
        result = first_occurrence + timedelta(weeks=n - 1)
        if result.month != month:
            return None
        return result
    elif n < 0:
        # Find last occurrence of weekday in month
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


def parse_byday(byday_str):
    """Parse BYDAY value like '4TU', '-1MO', 'TU,TH' into list of (n, weekday) tuples.
    n=0 means 'every occurrence of this weekday'.
    """
    result = []
    for part in byday_str.split(","):
        part = part.strip()
        if len(part) >= 2:
            day_code = part[-2:].upper()
            prefix = part[:-2]
            weekday = BYDAY_MAP.get(day_code)
            if weekday is not None:
                n = int(prefix) if prefix else 0
                result.append((n, weekday))
    return result


def expand_recurring_event(start_dt, end_dt, is_all_day, rrule, now, end_range, exdates=None):
    """Expand a recurring event into individual occurrences within the date range.
    
    Supports FREQ=DAILY/WEEKLY/MONTHLY/YEARLY with BYDAY, INTERVAL, COUNT, UNTIL.
    Also handles EXDATE (excluded dates).
    """
    occurrences = []
    exdates = exdates or set()
    
    # Parse the RRULE
    freq = "DAILY"
    interval = 1
    count = None
    until = None
    byday = []
    
    parts = rrule.split(";")
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            if key == "FREQ":
                freq = value.upper()
            elif key == "INTERVAL":
                try:
                    interval = int(value)
                except:
                    interval = 1
            elif key == "COUNT":
                try:
                    count = int(value)
                except:
                    count = None
            elif key == "UNTIL":
                try:
                    until = datetime.strptime(value[:8], "%Y%m%d")
                    until = until.replace(tzinfo=timezone.utc)
                except:
                    until = None
            elif key == "BYDAY":
                byday = parse_byday(value)
    
    # Calculate duration
    duration = end_dt - start_dt if end_dt else timedelta(hours=1)
    
    # For MONTHLY+BYDAY, generate occurrences differently
    if freq == "MONTHLY" and byday:
        # Generate month by month
        year = start_dt.year
        month = start_dt.month
        occ_count = 0
        max_months = 200  # Safety limit
        months_checked = 0
        
        while months_checked < max_months:
            for n, weekday in byday:
                if n != 0:
                    # Specific nth weekday (e.g., 4TU = 4th Tuesday)
                    candidate_date = nth_weekday_of_month(year, month, weekday, n)
                    if candidate_date is None:
                        continue
                    # Combine with original time
                    candidate = candidate_date.replace(
                        hour=start_dt.hour,
                        minute=start_dt.minute,
                        second=start_dt.second,
                        tzinfo=start_dt.tzinfo
                    )
                else:
                    # Every occurrence of this weekday in the month - skip for now
                    continue
                
                # Skip if before start
                if candidate < start_dt:
                    continue
                
                # Check UNTIL
                if until and candidate > until:
                    return occurrences
                
                # Check if excluded
                candidate_date_str = candidate.strftime("%Y%m%d")
                if candidate_date_str in exdates:
                    occ_count += 1
                    if count and occ_count >= count:
                        return occurrences
                    continue
                
                # Include if in range
                if candidate >= now - timedelta(days=1) and candidate <= end_range:
                    occ_end = candidate + duration
                    occurrences.append((candidate, occ_end))
                
                occ_count += 1
                if count and occ_count >= count:
                    return occurrences
                
                if candidate > end_range:
                    return occurrences
            
            # Advance by interval months
            month += interval
            while month > 12:
                month -= 12
                year += 1
            months_checked += 1
        
        return occurrences
    
    # For WEEKLY+BYDAY, generate by week
    if freq == "WEEKLY" and byday:
        # Start from the beginning of the week containing start_dt
        current = start_dt
        occ_count = 0
        max_occurrences = 500
        
        while current <= end_range and occ_count < max_occurrences:
            # Check each BYDAY
            for n, weekday in byday:
                # Find this weekday in the current week
                days_ahead = weekday - current.weekday()
                candidate = current + timedelta(days=days_ahead)
                
                if candidate < start_dt:
                    continue
                if until and candidate > until:
                    return occurrences
                
                candidate_date_str = candidate.strftime("%Y%m%d")
                if candidate_date_str in exdates:
                    continue
                
                if candidate >= now - timedelta(days=1) and candidate <= end_range:
                    occ_end = candidate + duration
                    occurrences.append((candidate, occ_end))
                
                occ_count += 1
                if count and occ_count >= count:
                    return occurrences
            
            current = current + timedelta(weeks=interval)
        
        return occurrences
    
    # Standard generation (DAILY, WEEKLY without BYDAY, YEARLY, MONTHLY without BYDAY)
    current = start_dt
    max_occurrences = 200
    occ_count = 0
    
    while current <= end_range and occ_count < max_occurrences:
        # Check if excluded
        candidate_date_str = current.strftime("%Y%m%d")
        
        if candidate_date_str not in exdates:
            # Include if occurrence is in range
            if current >= now - timedelta(days=1):
                occ_end = current + duration
                if current <= end_range:
                    occurrences.append((current, occ_end))
        
        # Move to next occurrence
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
                # Handle Feb 29 in non-leap years
                current = current.replace(year=current.year + interval, day=28)
        else:
            # Unknown frequency - stop to avoid infinite loops
            break
        
        occ_count += 1
        if count and occ_count >= count:
            break
        if until and current > until:
            break
    
    return occurrences


def parse_ical(ical_text, calendar_color, calendar_name):
    """Parse iCal text and extract events within the next 10 days, including recurring events.
    
    Two-pass approach:
    1. Collect all VEVENT blocks (both master recurring events and RECURRENCE-ID overrides)
    2. Process master events, using overrides to replace specific occurrences
    """
    now = datetime.now(timezone.utc)
    # Use start of today (midnight UTC) so all of today's events show,
    # even if they already occurred earlier today
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_range = today_midnight + timedelta(days=10)
    
    lines = unfold_ical(ical_text)
    
    # First pass: collect all raw events
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
                        ex = ex.strip()
                        date_part = ex[:8]
                        if "exdates" not in event:
                            event["exdates"] = set()
                        event["exdates"].add(date_part)
            elif line.startswith("RECURRENCE-ID"):
                if ":" in line:
                    event["recurrence_id"] = line.split(":", 1)[1].strip()[:8]
            elif line.startswith("UID:"):
                event["uid"] = line[4:].strip()
    
    # Separate master events (with RRULE) from override events (with RECURRENCE-ID)
    # Group by UID
    masters = {}   # uid -> event dict (has RRULE)
    overrides = {} # uid -> {date_str -> event dict} (has RECURRENCE-ID)
    singles = []   # events without UID or RRULE
    
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
    
    # Process master recurring events
    for uid, ev in masters.items():
        dtstart = ev.get("dtstart", "")
        dtend = ev.get("dtend", "")
        rrule = ev.get("rrule", "")
        exdates = ev.get("exdates", set())
        
        # Also add override dates to exdates (they'll be added back as overrides)
        uid_overrides = overrides.get(uid, {})
        all_exdates = exdates | set(uid_overrides.keys())
        
        start_dt, is_all_day = parse_ical_datetime(dtstart, ev.get("dtstart_param", ""))
        end_dt, _ = parse_ical_datetime(dtend, ev.get("dtend_param", "")) if dtend else (None, False)
        
        if start_dt is None:
            continue
        
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt is None:
            end_dt = start_dt + timedelta(hours=1)
        
        recurring_occurrences = expand_recurring_event(
            start_dt, end_dt, is_all_day, rrule, today_midnight, end_range, all_exdates
        )
        for occ_start, occ_end in recurring_occurrences:
            events.append(make_evt_from(ev, occ_start, occ_end, is_all_day))
        
        # Add override occurrences that fall in range
        for date_str, override_ev in uid_overrides.items():
            ov_dtstart = override_ev.get("dtstart", "")
            ov_dtend = override_ev.get("dtend", "")
            ov_start, ov_all_day = parse_ical_datetime(ov_dtstart, override_ev.get("dtstart_param", ""))
            ov_end, _ = parse_ical_datetime(ov_dtend, override_ev.get("dtend_param", "")) if ov_dtend else (None, False)
            
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
    
    # Process single (non-recurring) events
    for ev in singles:
        dtstart = ev.get("dtstart", "")
        dtend = ev.get("dtend", "")
        
        start_dt, is_all_day = parse_ical_datetime(dtstart, ev.get("dtstart_param", ""))
        end_dt, _ = parse_ical_datetime(dtend, ev.get("dtend_param", "")) if dtend else (None, False)
        
        if start_dt is None:
            continue
        
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt and end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt is None:
            end_dt = start_dt + timedelta(hours=1)
        
        if is_all_day and end_dt and (end_dt - start_dt).days > 1:
            # Multi-day all-day event: create one entry per day it spans
            span_end = end_dt - timedelta(days=1)
            current_day = start_dt
            while current_day <= span_end:
                if current_day.tzinfo is None:
                    current_day_aware = current_day.replace(tzinfo=timezone.utc)
                else:
                    current_day_aware = current_day
                if current_day_aware >= today_midnight and current_day_aware <= end_range:
                    events.append(make_evt_from(ev, current_day, current_day + timedelta(days=1), True))
                current_day = current_day + timedelta(days=1)
        else:
            # Include if event starts today or later (show all of today's events)
            if start_dt >= today_midnight and start_dt <= end_range:
                events.append(make_evt_from(ev, start_dt, end_dt, is_all_day))
    
    return events


def unescape_ical_text(text):
    """Unescape iCal text escapes: \\, \\; \\n \\N \\\\"""
    if not text:
        return text
    text = text.replace("\\,", ",")
    text = text.replace("\\;", ";")
    text = text.replace("\\n", " ").replace("\\N", " ")
    text = text.replace("\\\\", "\\")
    return text.strip()


def get_calendar_name_from_ical(ical_text):
    """Extract calendar name from iCal X-WR-CALNAME property."""
    lines = unfold_ical(ical_text)
    for line in lines:
        if line.startswith("X-WR-CALNAME:"):
            return line[13:].strip()
    return "Calendar"


def fetch_calendar_events():
    """Fetch events from all configured Google Calendars."""
    all_events = []
    
    for cal in CALENDARS:
        cal_id = cal["id"]
        color = cal["color"]
        url = f"https://calendar.google.com/calendar/ical/{urllib.parse.quote(cal_id, safe='@')}/public/basic.ics"
        
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ChurchCalendar/1.0)"
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                ical_text = response.read().decode("utf-8", errors="replace")
                cal_name = get_calendar_name_from_ical(ical_text)
                cal_events = parse_ical(ical_text, color, cal_name)
                all_events.extend(cal_events)
                logger.info(f"calendar_fetch_success calendar={cal_name} events={len(cal_events)}")
        except Exception as e:
            logger.error(f"calendar_fetch_failed calendar_id={cal_id} error={e}")
    
    # Sort by start time
    all_events.sort(key=lambda e: e["start"])
    return all_events


def fetch_cached_calendar_events():
    """Fetch events using CalendarCache when available for faster API responses."""
    global CALENDAR_CACHE_INSTANCE

    if not IMAGE_OPTIMIZATION_AVAILABLE:
        return fetch_calendar_events()

    try:
        if CALENDAR_CACHE_INSTANCE is None:
            CALENDAR_CACHE_INSTANCE = CalendarCache()
        return CALENDAR_CACHE_INSTANCE.fetch_calendar_events()
    except Exception as e:
        logger.warning(f"cached_fetch_failed_fallback_live error={e}")
        return fetch_calendar_events()


def parse_event_datetime(value):
    """Parse event datetime strings into aware datetimes when possible."""
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def build_service_restart_schedule(events, now=None, gap_minutes=15):
    """Build restart schedule from Services events using contiguous block rules."""
    now = now or datetime.now(timezone.utc)
    gap = timedelta(minutes=gap_minutes)

    service_events = []
    for event in events:
        if event.get("calendar") != "Services" or event.get("allDay"):
            continue

        start_dt = parse_event_datetime(event.get("start"))
        end_dt = parse_event_datetime(event.get("end"))
        if not start_dt or not end_dt:
            continue
        if end_dt < start_dt:
            end_dt = start_dt

        service_events.append({
            "summary": event.get("summary", ""),
            "start": start_dt,
            "end": end_dt,
        })

    service_events.sort(key=lambda item: item["start"])

    blocks = []
    for item in service_events:
        if not blocks:
            blocks.append({
                "start": item["start"],
                "end": item["end"],
                "source_event_summary": item["summary"],
                "source_event_start": item["start"],
                "event_count": 1,
                "suppressed": [],
            })
            continue

        current = blocks[-1]
        if item["start"] <= current["end"] + gap:
            current["end"] = max(current["end"], item["end"])
            current["event_count"] += 1
            current["suppressed"].append({
                "summary": item["summary"],
                "start": item["start"],
                "end": item["end"],
            })
        else:
            blocks.append({
                "start": item["start"],
                "end": item["end"],
                "source_event_summary": item["summary"],
                "source_event_start": item["start"],
                "event_count": 1,
                "suppressed": [],
            })

    next_block = None
    for block in blocks:
        # Include currently active blocks so slight poll delays do not miss trigger windows.
        if block["end"] > now:
            next_block = block
            break

    response = {
        "generated_at": now.isoformat(),
        "timezone": "America/Los_Angeles",
        "gap_minutes": gap_minutes,
        "next_restart": None,
    }

    if next_block:
        trigger_id = f"{next_block['start'].isoformat()}|{next_block['end'].isoformat()}"
        response["next_restart"] = {
            "trigger_id": trigger_id,
            "restart_at": next_block["start"].isoformat(),
            "source_event_summary": next_block["source_event_summary"],
            "source_event_start": next_block["source_event_start"].isoformat(),
            "block_end": next_block["end"].isoformat(),
            "block_event_count": next_block["event_count"],
            "suppressed_by_back_to_back_rule": len(next_block["suppressed"]) > 0,
        }

    return response


class CalendarHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves the webpage and calendar data API."""
    
    def __init__(self, *args, **kwargs):
        # Extract image_manager from kwargs if available
        self.image_manager = kwargs.pop('image_manager', None)
        super().__init__(*args, directory=os.path.dirname(os.path.abspath(__file__)) or ".", **kwargs)
    
    def do_GET(self):
        global LAST_LOGGED_RESTART_TRIGGER
        path = self.path.split("?", 1)[0]

        if path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            
            logger.info("api_events_fetch_start")
            events = fetch_calendar_events()
            logger.info(f"api_events_fetch_complete events={len(events)}")
            
            self.wfile.write(json.dumps(events).encode("utf-8"))

        elif path == "/api/service-restart-schedule":
            started = time.perf_counter()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()

            events = fetch_cached_calendar_events()
            schedule = build_service_restart_schedule(events, gap_minutes=15)
            self.wfile.write(json.dumps(schedule).encode("utf-8"))
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            next_restart = schedule.get("next_restart") or {}
            trigger_id = next_restart.get("trigger_id", "__none__")
            if trigger_id != LAST_LOGGED_RESTART_TRIGGER:
                restart_at = next_restart.get("restart_at", "none")
                logger.info(
                    f"api_service_restart_schedule_changed duration_ms={elapsed_ms} "
                    f"events={len(events)} trigger_id={trigger_id} restart_at={restart_at}"
                )
                LAST_LOGGED_RESTART_TRIGGER = trigger_id
        
        elif path == "/api/images":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=300")
            self.end_headers()
            
            if self.image_manager:
                logger.info("api_images_fetch_start")
                images = self.image_manager.get_all_images()
                logger.info(f"api_images_fetch_complete images={len(images)}")
                self.wfile.write(json.dumps(images).encode("utf-8"))
            else:
                # Return empty array if no image manager
                self.wfile.write(json.dumps([]).encode("utf-8"))
        
        elif path == "/" or path == "":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        if "/api/" not in str(args[0]):
            pass


def main():
    global CALENDAR_CACHE_INSTANCE
    logger.info("server_start church=St.Demetrios process=calendar-display")
    
    # Initialize optimization systems at startup
    logger.info("initializing_optimizations")
    
    # 1. Optimize images at service start time
    if IMAGE_OPTIMIZATION_AVAILABLE:
        try:
            optimizer = ImageOptimizer()
            optimized_count = len(optimizer.optimize_all_images())
            logger.info(f"image_optimization_complete images={optimized_count}")
        except Exception as e:
            logger.error(f"image_optimization_failed error={e}")
    
    # 2. Cache calendar data at service start time (no periodic refresh)
    if IMAGE_OPTIMIZATION_AVAILABLE:
        try:
            CALENDAR_CACHE_INSTANCE = CalendarCache()
            cached_events = CALENDAR_CACHE_INSTANCE.fetch_calendar_events()
            logger.info(f"calendar_caching_complete events={len(cached_events)}")
        except Exception as e:
            logger.error(f"calendar_caching_failed error={e}")
            cached_events = []
    else:
        cached_events = []

    # Schedule a single deferred retry if startup fetch returned no events
    if not cached_events and CALENDAR_CACHE_INSTANCE is not None:
        def _deferred_calendar_retry():
            global CALENDAR_CACHE_INSTANCE
            try:
                if CALENDAR_CACHE_INSTANCE is None:
                    return
                CALENDAR_CACHE_INSTANCE.cache = []
                events = CALENDAR_CACHE_INSTANCE.fetch_calendar_events()
                if events:
                    logger.info(f"deferred_calendar_retry_succeeded events={len(events)}")
                else:
                    logger.warning("deferred_calendar_retry_returned_empty")
            except Exception as e:
                logger.error(f"deferred_calendar_retry_failed error={e}")

        retry_timer = threading.Timer(60, _deferred_calendar_retry)
        retry_timer.daemon = True
        retry_timer.start()
        logger.info("deferred_calendar_retry_scheduled delay_seconds=60")

    logger.info(f"server_listening port={PORT}")
    logger.info(f"calendar_sources count={len(CALENDARS)}")
    
    if IMAGE_SOURCES_AVAILABLE:
        # Initialize image source manager
        image_manager = ImageSourceManager()
        local_config = image_manager.config.get("local_files", {})
        if local_config.get("enabled", False):
            folder_path = local_config.get("folder_path", "./images/")
            logger.info(f"image_sources_configured local_files_path={folder_path}")
        else:
            logger.info("image_sources_not_configured")
    else:
        logger.info("image_functionality_disabled")
    
    logger.info("performance_optimizations images_startup=true calendar_cached=true network_periodic=false")
    
    try:
        # Pass optimization systems to handler
        handler_class = CalendarHandler
        if IMAGE_SOURCES_AVAILABLE:
            handler_class = lambda *args, **kwargs: CalendarHandler(*args, image_manager=image_manager, **kwargs)
        
        # Add optimized images directory to serve static files
        import os
        import http.server
        import socketserver
        
        # Custom handler to serve optimized images and thumbnails
        class OptimizedImageHandler(CalendarHandler):
            def do_GET(self):
                if self.path.startswith('/optimized/'):
                    # Serve only flat files from images/optimized
                    requested_name = urllib.parse.unquote(os.path.basename(self.path.split('?', 1)[0]))
                    optimized_path = os.path.join('images', 'optimized', requested_name)
                    if os.path.isfile(optimized_path):
                        self.send_response(200)
                        self.send_header('Content-type', 'image/webp')
                        self.send_header('Cache-Control', 'public, max-age=86400')
                        self.end_headers()
                        with open(optimized_path, 'rb') as f:
                            self.wfile.write(f.read())
                        return
                    else:
                        self.send_error(404, 'File not found')
                        return
                elif self.path.startswith('/thumbnails/'):
                    # Serve only flat files from images/thumbnails
                    requested_name = urllib.parse.unquote(os.path.basename(self.path.split('?', 1)[0]))
                    thumbnail_path = os.path.join('images', 'thumbnails', requested_name)
                    if os.path.isfile(thumbnail_path):
                        self.send_response(200)
                        self.send_header('Content-type', 'image/webp')
                        self.send_header('Cache-Control', 'public, max-age=86400')
                        self.end_headers()
                        with open(thumbnail_path, 'rb') as f:
                            self.wfile.write(f.read())
                        return
                    else:
                        self.send_error(404, 'File not found')
                        return
                super().do_GET()
        
        # Use the optimized handler
        if IMAGE_SOURCES_AVAILABLE:
            handler_class = lambda *args, **kwargs: OptimizedImageHandler(*args, image_manager=image_manager, **kwargs)
        else:
            handler_class = OptimizedImageHandler
        
        with http.server.HTTPServer(("", PORT), handler_class) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("server_stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
