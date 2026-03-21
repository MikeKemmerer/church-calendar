#!/usr/bin/env python3
"""Debug script to check what events are being fetched from Google Calendars."""

import json
import os
import urllib.request
import logging
import time
from datetime import datetime, timedelta, timezone

logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("church-calendar.debug")

def _load_calendars():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json'), 'r') as f:
            cfg = json.load(f)
            cals = cfg.get("calendars", [])
            if cals:
                return [{"id": c["id"], "name": f"Cal{i+1}"} for i, c in enumerate(cals)]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Could not load calendars from config.json: {e}")
    return []

CALENDARS = _load_calendars()

def unfold_ical(text):
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    unfolded = []
    for line in lines:
        if line.startswith(' ') or line.startswith('\t'):
            if unfolded:
                unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded

# Target date: Feb 21, 2026
target = "20260221"

for cal in CALENDARS:
    cal_id = cal["id"]
    url = f"https://calendar.google.com/calendar/ical/{urllib.request.quote(cal_id, safe='@')}/public/basic.ics"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            ical_text = response.read().decode("utf-8", errors="replace")
        
        lines = unfold_ical(ical_text)
        
        # Get calendar name
        cal_name = cal["name"]
        for line in lines:
            if line.startswith("X-WR-CALNAME:"):
                cal_name = line[13:].strip()
                break
        
        # Find events on Feb 21
        in_event = False
        event = {}
        found_events = []
        
        for line in lines:
            if line.strip() == "BEGIN:VEVENT":
                in_event = True
                event = {}
            elif line.strip() == "END:VEVENT":
                in_event = False
                if event.get("dtstart", "").replace(";VALUE=DATE", "").replace(":", "").startswith(target):
                    found_events.append(event)
                event = {}
            elif in_event:
                if line.startswith("SUMMARY:"):
                    event["summary"] = line[8:].strip()
                elif line.startswith("DTSTART"):
                    event["dtstart"] = line.split(":", 1)[1].strip() if ":" in line else ""
                elif line.startswith("DTEND"):
                    event["dtend"] = line.split(":", 1)[1].strip() if ":" in line else ""
                elif line.startswith("RRULE:"):
                    event["rrule"] = line[6:].strip()
        
        if found_events:
            logger.info(f"calendar_events_found calendar={cal_name} count={len(found_events)}")
            for e in found_events:
                logger.info(f"event dtstart={e.get('dtstart','')} summary={e.get('summary','')}")
        else:
            logger.info(f"calendar_no_target_events calendar={cal_name} target={target}")
            
    except Exception as e:
        logger.error(f"calendar_fetch_failed calendar_id={cal_id} error={e}")

logger.info("checking_rrule_events target=20260221 calendar=Cal1")

cal_id = CALENDARS[0]["id"] if CALENDARS else ""
if not cal_id:
    logger.error("No calendars configured for RRULE check")
    raise SystemExit(1)
url = f"https://calendar.google.com/calendar/ical/{urllib.request.quote(cal_id, safe='@')}/public/basic.ics"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as response:
    ical_text = response.read().decode("utf-8", errors="replace")

lines = unfold_ical(ical_text)
in_event = False
event = {}
recurring = []

for line in lines:
    if line.strip() == "BEGIN:VEVENT":
        in_event = True
        event = {}
    elif line.strip() == "END:VEVENT":
        in_event = False
        if event.get("rrule"):
            recurring.append(event.copy())
        event = {}
    elif in_event:
        if line.startswith("SUMMARY:"):
            event["summary"] = line[8:].strip()
        elif line.startswith("DTSTART"):
            event["dtstart"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("RRULE:"):
            event["rrule"] = line[6:].strip()

logger.info(f"recurring_events_found calendar=Cal1 count={len(recurring)}")
for e in recurring[:10]:
    logger.info(f"recurring_event dtstart={e.get('dtstart','')} rrule={e.get('rrule','')} summary={e.get('summary','')}")
