"""ntfy_notify - send push notifications through ntfy.sh, with dedupe.

The topic is the only secret on public ntfy.sh, so it must never be
committed. It is read from the NTFY_TOPIC environment variable, or from the
file at NTFY_TOPIC_FILE (default /etc/church-calendar/ntfy-topic).

Typical use is via NtfyLoggingHandler, which forwards ERROR+ log records from
any "church-calendar.*" logger as alerts, deduped so a repeating error does
not spam the same alert more than once per dedupe window.
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

TOPIC_FILE = os.environ.get("NTFY_TOPIC_FILE", "/etc/church-calendar/ntfy-topic")
SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
DEDUPE_DIR = os.environ.get("NTFY_DEDUPE_DIR", os.path.join(tempfile.gettempdir(), "church-calendar-ntfy"))
DEDUPE_SECONDS_DEFAULT = int(os.environ.get("NTFY_DEDUPE_SECONDS", "900"))
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")

# Automatic alerts (uncaught exceptions, logged errors, service crashes) only
# fire while a church service is active, per this same server's own
# service-restart schedule. Pass always=True (on-demand digests, scheduled
# reachability checks) to bypass the gate. If the schedule can't be read or
# parsed, the gate fails open so a real outage is never silently swallowed.
SERVICE_WINDOW_URL = os.environ.get(
    "SERVICE_WINDOW_URL", "http://localhost:8000/api/service-restart-schedule"
)


def _in_service_window() -> bool:
    try:
        with urllib.request.urlopen(SERVICE_WINDOW_URL, timeout=4) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        nr = data.get("next_restart")
        if not nr:
            return False
        start = datetime.fromisoformat(nr["restart_at"])
        end = datetime.fromisoformat(nr["block_end"])
        now = datetime.now(timezone.utc)
        return start <= now <= end
    except Exception:
        return True


def _topic() -> str | None:
    topic = os.environ.get("NTFY_TOPIC", "")
    if not topic and os.path.isfile(TOPIC_FILE):
        try:
            with open(TOPIC_FILE, "r", encoding="utf-8") as fh:
                topic = fh.read().strip()
        except OSError:
            topic = ""
    return topic if _TOPIC_RE.match(topic or "") else None


def _should_send(dedupe_key: str, dedupe_seconds: int) -> bool:
    if dedupe_seconds <= 0:
        return True
    try:
        os.makedirs(DEDUPE_DIR, exist_ok=True)
        digest = hashlib.md5(dedupe_key.encode("utf-8")).hexdigest()
        marker = os.path.join(DEDUPE_DIR, digest)
        now = time.time()
        if os.path.isfile(marker):
            last = os.path.getmtime(marker)
            if now - last < dedupe_seconds:
                return False
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(str(now))
    except OSError:
        pass
    return True


def send(message: str, title: str = "church-calendar", priority: str = "default",
         tags: str = "", dedupe_key: str | None = None,
         dedupe_seconds: int = DEDUPE_SECONDS_DEFAULT, always: bool = False) -> bool:
    """Send one ntfy notification. Never raises; returns True if sent."""
    if not message:
        return False
    if not always and not _in_service_window():
        return False
    topic = _topic()
    if not topic:
        return False
    if not _should_send(dedupe_key or message, dedupe_seconds):
        return False

    headers = {"Priority": priority, "Title": title}
    if tags:
        headers["Tags"] = tags
    try:
        req = urllib.request.Request(
            f"{SERVER}/{topic}", data=message.encode("utf-8"), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except (urllib.error.URLError, OSError):
        return False


class NtfyLoggingHandler(logging.Handler):
    """Forward ERROR+ log records as ntfy alerts, deduped per logger+message."""

    def __init__(self, title: str = "church-calendar", level: int = logging.ERROR) -> None:
        super().__init__(level=level)
        self._title = title

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            send(
                message,
                title=f"{self._title} ({record.levelname})",
                priority="high",
                dedupe_key=f"{record.name}:{record.getMessage()}",
            )
        except Exception:
            # A broken alert path must never break logging or crash the caller.
            pass
