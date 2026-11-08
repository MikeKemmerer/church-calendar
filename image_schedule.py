#!/usr/bin/env python3
"""Per-image display schedule for the calendar's images folder.

The schedule lives in ``<images>/image-schedule.json`` and is the source of truth for when each
image is shown. Files are added to it automatically from their names: a leading
``YYYY-MM-DD `` is the last day the image shows, and ``[auto-archive]`` just before the
extension moves it to ``images/archive/`` the day after. Dates of 2099 or later mean "never expires".
A ``show_from`` start date can only be set through this module (or by editing the file).

Every change takes one lock (``<images>/.image-schedule.lock``) so the service, the sweep and
external tools never overwrite each other. Set IMAGE_SCHEDULE_LOCK_HELD=1 when the caller
already holds that lock.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

logger = logging.getLogger("church-calendar.image-schedule")

SCHEDULE_NAME = "image-schedule.json"
LOCK_NAME = ".image-schedule.lock"
ARCHIVE_DIR = "archive"
DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
NEVER_EXPIRES_YEAR = 2099
AUTO_ARCHIVE_MARKER = "[auto-archive]"

_NAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<rest>.+?)(?P<auto> \[auto-archive\])?(?P<ext>\.[A-Za-z0-9]+)$",
    re.IGNORECASE,
)


class ScheduleError(ValueError):
    pass


def parse_day(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ScheduleError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def entry_from_filename(name: str) -> dict[str, Any]:
    """Seed schedule values from the file name; files without a date prefix never expire."""
    entry: dict[str, Any] = {"show_from": None, "remove_after": None, "auto_archive": False, "origin": "manual"}
    match = _NAME_RE.match(name)
    if not match:
        return entry
    entry["origin"] = "filename"
    entry["auto_archive"] = bool(match.group("auto"))
    try:
        end = date.fromisoformat(match.group("date"))
    except ValueError:
        return entry
    if end.year < NEVER_EXPIRES_YEAR:
        entry["remove_after"] = end.isoformat()
    return entry


def is_active(entry: dict[str, Any], today: date) -> bool:
    start = parse_day(entry.get("show_from"), "show_from")
    end = parse_day(entry.get("remove_after"), "remove_after")
    if start and today < start:
        return False
    if end and today > end:
        return False
    return True


def state_of(entry: dict[str, Any], today: date) -> str:
    start = parse_day(entry.get("show_from"), "show_from")
    end = parse_day(entry.get("remove_after"), "remove_after")
    if start and today < start:
        return "scheduled"
    if end and today > end:
        return "expired"
    return "persistent" if end is None and start is None else "active"


def today_local(timezone_name: str = DEFAULT_TIMEZONE) -> date:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(timezone_name)).date()
        except Exception:
            pass
    return datetime.now().astimezone().date()


def seconds_until_hour(hour: int, timezone_name: str = DEFAULT_TIMEZONE) -> float:
    """Seconds from now until the next local time of day at ``hour``:00."""
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = None
    now = datetime.now(tz) if tz else datetime.now().astimezone()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


@contextlib.contextmanager
def _lock(images_dir: Path) -> Iterator[None]:
    if os.environ.get("IMAGE_SCHEDULE_LOCK_HELD") == "1":
        yield
        return
    images_dir.mkdir(parents=True, exist_ok=True)
    with open(images_dir / LOCK_NAME, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _load(images_dir: Path, repair: bool = False) -> dict[str, Any]:
    """Read the schedule; a missing or malformed file reads as empty, any other read error propagates."""
    path = images_dir / SCHEDULE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except ValueError:
        if repair:
            logger.error("image_schedule_malformed file=%s; keeping a copy and rebuilding from file names", path)
            with contextlib.suppress(OSError):
                os.replace(path, images_dir / f"{SCHEDULE_NAME}.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
        data = {}
    images = data.get("images") if isinstance(data, dict) else None
    return {"version": 1, "images": images if isinstance(images, dict) else {}}


def _save(images_dir: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".image-schedule-", dir=images_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, images_dir / SCHEDULE_NAME)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _image_files(images_dir: Path, extensions: tuple[str, ...]) -> list[str]:
    exts = {e.lower() for e in extensions}
    try:
        entries = list(images_dir.iterdir())
    except FileNotFoundError:
        return []
    return sorted(p.name for p in entries if p.is_file() and p.suffix.lower() in exts)


def _sync_locked(images_dir: Path, extensions: tuple[str, ...]) -> dict[str, Any]:
    data = _load(images_dir, repair=True)
    images = data["images"]
    present = set(_image_files(images_dir, extensions))
    changed = False
    for name in present - images.keys():
        images[name] = entry_from_filename(name)
        changed = True
    # Prune only files that are really gone, not ones an extension filter happens to hide.
    for name in [n for n in images if not (images_dir / n).is_file()]:
        del images[name]
        changed = True
    if changed:
        _save(images_dir, data)
    return data


def sync(images_dir: Path | str, extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> dict[str, Any]:
    """Add newly seen files (seeded from their names), drop entries for files that are gone."""
    images_dir = Path(images_dir)
    with _lock(images_dir):
        return _sync_locked(images_dir, extensions)


def active_names(images_dir: Path | str, today: date, extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> set[str]:
    data = sync(images_dir, extensions)
    return {name for name, entry in data["images"].items() if is_active(entry, today)}


def visible_names(images_dir: Path | str, today: date, extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> set[str]:
    """Names to show today; on a read-only folder (no lock or schedule writes) the stored schedule still applies."""
    try:
        return active_names(images_dir, today, extensions)
    except OSError as exc:
        logger.warning("image_schedule_read_only error=%s; using the stored schedule without writing", exc)
        rows = listing(images_dir, today, extensions, read_only=True)
        return {row["filename"] for row in rows if row["state"] in ("active", "persistent")}


def set_entry(
    images_dir: Path | str,
    name: str,
    *,
    show_from: str | None = None,
    remove_after: str | None = None,
    auto_archive: bool = False,
    persistent: bool = False,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
) -> dict[str, Any]:
    images_dir = Path(images_dir)
    if Path(name).name != name or not name:
        raise ScheduleError("name must be a bare file name")
    start = parse_day(show_from, "show_from")
    end = parse_day(remove_after, "remove_after")
    if persistent:
        start, end, auto_archive = None, None, False
    elif auto_archive and end is None:
        raise ScheduleError("auto-archive needs a remove-after date")
    if start and end and end < start:
        raise ScheduleError("remove-after cannot be before show-from")
    with _lock(images_dir):
        data = _sync_locked(images_dir, extensions)
        if name not in data["images"]:
            raise ScheduleError(f"{name} is not in the images folder")
        entry = {
            "show_from": start.isoformat() if start else None,
            "remove_after": end.isoformat() if end else None,
            "auto_archive": bool(auto_archive),
            "origin": "ui",
        }
        data["images"][name] = entry
        _save(images_dir, data)
        return entry


def drop_entry(images_dir: Path | str, name: str) -> None:
    images_dir = Path(images_dir)
    with _lock(images_dir):
        data = _load(images_dir, repair=True)
        if data["images"].pop(name, None) is not None:
            _save(images_dir, data)


def sweep(images_dir: Path | str, today: date, extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> list[str]:
    """Move auto-archive images whose last day has passed into images/archive/."""
    images_dir = Path(images_dir)
    archived: list[str] = []
    with _lock(images_dir):
        data = _sync_locked(images_dir, extensions)
        for name, entry in sorted(data["images"].items()):
            end = parse_day(entry.get("remove_after"), "remove_after")
            if not (entry.get("auto_archive") and end and today > end):
                continue
            source = images_dir / name
            if not source.is_file():
                continue
            archive = images_dir / ARCHIVE_DIR
            archive.mkdir(exist_ok=True)
            target = archive / name
            counter = 1
            while target.exists():
                target = archive / f"{source.stem}-{counter}{source.suffix}"
                counter += 1
            shutil.move(str(source), str(target))
            del data["images"][name]
            archived.append(name)
        if archived:
            _save(images_dir, data)
    return archived


def listing(
    images_dir: Path | str,
    today: date,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    read_only: bool = False,
) -> list[dict[str, Any]]:
    """Every image with its schedule and state; read_only never writes (for callers without write access)."""
    images_dir = Path(images_dir)
    if read_only:
        stored = _load(images_dir)["images"]
        data = {"images": {n: stored.get(n) or entry_from_filename(n) for n in _image_files(images_dir, extensions)}}
    else:
        data = sync(images_dir, extensions)
    rows = []
    for name, entry in sorted(data["images"].items()):
        rows.append({"filename": name, **entry, "state": state_of(entry, today)})
    return rows


def resolve_images_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    base = Path(__file__).resolve().parent
    folder = "./images/"
    try:
        folder = json.loads((base / "config.json").read_text(encoding="utf-8")).get("local_files", {}).get("folder_path", folder)
    except (OSError, ValueError):
        pass
    path = Path(folder)
    return path if path.is_absolute() else base / path


def config_timezone() -> str:
    try:
        cfg = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
        return str(cfg.get("calendar", {}).get("timezone") or DEFAULT_TIMEZONE)
    except (OSError, ValueError):
        return DEFAULT_TIMEZONE


def run_optimizer() -> None:
    """Regenerate derivatives so files that left images/ lose their optimized copies."""
    script = Path(__file__).resolve().parent / "image_optimizer.py"
    if script.is_file():
        subprocess.run([sys.executable, str(script)], cwd=script.parent, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the calendar image display schedule")
    parser.add_argument("--images-dir", help="images folder (default: from config.json)")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="print every image with its schedule and state as JSON")
    p_list.add_argument("--read-only", action="store_true", help="never write the schedule file")
    sub.add_parser("sync", help="add new files to the schedule and drop missing ones")
    p_set = sub.add_parser("set", help="set the schedule for one image")
    p_set.add_argument("filename")
    p_set.add_argument("--show-from")
    p_set.add_argument("--remove-after")
    p_set.add_argument("--auto-archive", action="store_true")
    p_set.add_argument("--persistent", action="store_true")
    p_drop = sub.add_parser("drop", help="forget the schedule entry for one image")
    p_drop.add_argument("filename")
    sub.add_parser("sweep", help="archive expired auto-archive images")
    args = parser.parse_args(argv)

    images_dir = resolve_images_dir(args.images_dir)
    today = parse_day(args.today, "--today") if args.today else today_local(config_timezone())
    try:
        if args.command == "list":
            print(json.dumps({"today": today.isoformat(), "images": listing(images_dir, today, read_only=args.read_only)}))
        elif args.command == "sync":
            sync(images_dir)
        elif args.command == "set":
            entry = set_entry(
                images_dir, args.filename, show_from=args.show_from, remove_after=args.remove_after,
                auto_archive=args.auto_archive, persistent=args.persistent,
            )
            print(json.dumps(entry))
        elif args.command == "drop":
            drop_entry(images_dir, args.filename)
        elif args.command == "sweep":
            archived = sweep(images_dir, today)
            if archived:
                run_optimizer()
            print(json.dumps({"archived": archived}))
    except ScheduleError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
