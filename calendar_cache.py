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
from datetime import datetime
import logging

from ical_parser import get_calendar_name_from_ical, parse_ical

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
                    cal_name = get_calendar_name_from_ical(ical_text)
                    cal_events = parse_ical(ical_text, color, cal_name)
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