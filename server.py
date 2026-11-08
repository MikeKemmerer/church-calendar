#!/usr/bin/env python3
"""
Church Calendar - Calendar Display Server
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

try:
    from ntfy_notify import NtfyLoggingHandler

    logging.getLogger("church-calendar").addHandler(NtfyLoggingHandler())

    def _notify_uncaught(exc_type, exc_value, exc_tb):
        logging.getLogger("church-calendar").critical(
            "uncaught_exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _notify_uncaught
except ImportError as e:
    logger.warning(f"ntfy alerting unavailable: {e}")


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
    import image_schedule
    import image_sources
    from image_sources import ImageSourceManager
    IMAGE_SOURCES_AVAILABLE = True
except ImportError:
    IMAGE_SOURCES_AVAILABLE = False
    logger.warning("image_sources.py not found. Image functionality disabled.")

IMAGE_SWEEP_HOUR = 3  # local hour of the nightly archive sweep

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


def _calendar_setting(key, default):
    """Read one integer from the config.json ``calendar`` section."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json'), 'r') as f:
            cal_cfg = json.load(f).get("calendar", {})
        value = int(cal_cfg.get(key, default))
        return value if value > 0 else default
    except (FileNotFoundError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return default


# The cache serves downstream schedulers; the Pi display only ever shows a short window.
CACHE_DAYS = _calendar_setting("cache_days", 90)


def resolve_day_limits(cache_days, default_days, configured_max):
    """Return (default, maximum) days a display may show; the maximum is a hard limit and never exceeds the cache."""
    maximum = min(configured_max or default_days, cache_days)
    return min(default_days, maximum), maximum


# display_days is the pre-rc.5 name of default_display_days.
DEFAULT_DISPLAY_DAYS, MAX_DISPLAY_DAYS = resolve_day_limits(
    CACHE_DAYS,
    _calendar_setting("default_display_days", _calendar_setting("display_days", 10)),
    _calendar_setting("max_display_days", 0),
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_RECORD = "/etc/church-calendar/installed-version.json"


def get_branding():
    """Display text from the config.json ``branding`` section, re-read per call so edits show on reload."""
    try:
        with open(os.path.join(APP_DIR, 'config.json'), 'r') as f:
            cfg = json.load(f).get("branding", {})
    except (OSError, ValueError, AttributeError):
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}

    def text(key, default):
        value = cfg.get(key)
        return value.strip()[:120] if isinstance(value, str) and value.strip() else default

    title = text("title", "Church Calendar")
    subtitle_template = text("subtitle", "Upcoming Events \u2022 Next {days} Days")
    return {
        "title": title,
        "subtitle": subtitle_template.replace("{days}", str(DEFAULT_DISPLAY_DAYS)),
        "subtitle_template": subtitle_template,
        "default_days": DEFAULT_DISPLAY_DAYS,
        "max_days": MAX_DISPLAY_DAYS,
        "page_title": text("page_title", "{title} - Calendar").replace("{title}", title),
    }


def get_version_info():
    """The installed release if the installer recorded one, else the VERSION file of this checkout."""
    try:
        with open(VERSION_RECORD, 'r') as f:
            record = json.load(f)
        return {"version": record.get("version"), "tag": record.get("tag")}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(APP_DIR, 'VERSION'), 'r') as f:
            return {"version": f.read().strip() or None, "tag": None}
    except OSError:
        return {"version": None, "tag": None}


IMAGE_FILE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def resolve_source_image(name):
    """The original image ``name`` in the configured folder, or None; only bare image file names qualify."""
    if not name or os.path.basename(name) != name or os.path.splitext(name)[1].lower() not in IMAGE_FILE_EXTENSIONS:
        return None
    path = image_schedule.resolve_images_dir(None) / name
    return path if path.is_file() else None


def image_preview_url(name):
    """Best available web path for an image: optimized copy, then thumbnail, then the original."""
    quoted = urllib.parse.quote(name)
    for folder, prefix in (("optimized", "/optimized/"), ("thumbnails", "/thumbnails/")):
        if os.path.exists(os.path.join(APP_DIR, "images", folder, name + ".webp")):
            return f"{prefix}{quoted}.webp"
    configured = os.path.realpath(image_schedule.resolve_images_dir(None))
    if configured != os.path.realpath(os.path.join(APP_DIR, "images")):
        return f"/source-images/{quoted}"
    return f"/images/{quoted}"


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
                cal_events = parse_ical(ical_text, color, cal_name, days=CACHE_DAYS)
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


def limit_events_to_days(events, days, now=None):
    """Trim cached events to a shorter window for the display."""
    if not days or days <= 0:
        return events

    now = now or datetime.now(timezone.utc)
    cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
    trimmed = []
    for event in events:
        start = parse_event_datetime(event.get("start"))
        if start is None or start <= cutoff:
            trimmed.append(event)
    return trimmed


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
            events = limit_events_to_days(fetch_cached_calendar_events(), MAX_DISPLAY_DAYS)
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
        
        elif path in ("/api/branding", "/api/version"):
            body = get_branding() if path == "/api/branding" else get_version_info()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))

        elif path == "/api/image-schedule":
            try:
                today = image_schedule.today_local(image_schedule.config_timezone())
                body = {
                    "today": today.isoformat(),
                    "images": [
                        {**row, "image": image_preview_url(row["filename"])}
                        for row in image_schedule.listing(image_schedule.resolve_images_dir(None), today, read_only=True)
                    ],
                }
                status = 200
            except Exception as e:
                logger.error(f"api_image_schedule_failed error={e}")
                body, status = {"error": "image schedule unavailable"}, 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))

        elif path == "/" or path == "":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        if "/api/" not in str(args[0]):
            pass


def run_image_sweep():
    """Archive auto-archive images whose last day has passed."""
    try:
        today = image_schedule.today_local(image_schedule.config_timezone())
        archived = image_schedule.sweep(image_schedule.resolve_images_dir(None), today)
        if archived:
            logger.info(f"image_schedule_archived count={len(archived)} files={archived}")
            if IMAGE_OPTIMIZATION_AVAILABLE:
                ImageOptimizer().optimize_all_images()
            image_sources.IMAGE_CACHE.clear()
    except Exception as e:
        logger.error(f"image_schedule_sweep_failed error={e}")


def schedule_nightly_image_sweep():
    delay = image_schedule.seconds_until_hour(IMAGE_SWEEP_HOUR, image_schedule.config_timezone())

    def _run_then_reschedule():
        run_image_sweep()
        schedule_nightly_image_sweep()

    timer = threading.Timer(delay, _run_then_reschedule)
    timer.daemon = True
    timer.start()
    logger.info(f"image_sweep_scheduled in_seconds={int(delay)}")


def main():
    global CALENDAR_CACHE_INSTANCE
    logger.info("server_start process=calendar-display")
    
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

    # 1b. Archive images past their end date now, and again every night
    if IMAGE_SOURCES_AVAILABLE:
        run_image_sweep()
        schedule_nightly_image_sweep()
    
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
                elif self.path.startswith('/source-images/'):
                    # Originals from the configured folder when it is not the app's own images/ folder
                    requested_name = urllib.parse.unquote(os.path.basename(self.path.split('?', 1)[0]))
                    source = resolve_source_image(requested_name)
                    if source is None:
                        self.send_error(404, 'File not found')
                        return
                    self.send_response(200)
                    self.send_header('Content-type', self.guess_type(requested_name))
                    self.send_header('Cache-Control', 'public, max-age=3600')
                    self.end_headers()
                    with open(source, 'rb') as f:
                        self.wfile.write(f.read())
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
