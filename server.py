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

from ical_parser import get_calendar_name_from_ical, parse_ical

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
            events = fetch_cached_calendar_events()
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
