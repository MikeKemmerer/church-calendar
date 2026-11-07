import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

import image_schedule as sched

TODAY = date(2026, 12, 1)


class ImageScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ.pop("IMAGE_SCHEDULE_LOCK_HELD", None)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, name):
        (self.dir / name).write_bytes(b"x")

    def test_filename_seeding(self):
        e = sched.entry_from_filename("2026-12-01 Rummage Sale [auto-archive].png")
        self.assertEqual((e["remove_after"], e["auto_archive"], e["show_from"]), ("2026-12-01", True, None))
        self.assertTrue(sched.entry_from_filename("2026-12-01 Sale [AUTO-ARCHIVE].PNG")["auto_archive"])
        self.assertFalse(sched.entry_from_filename("2026-12-01 Sale.png")["auto_archive"])

    def test_persistent_and_undated_names_never_expire(self):
        for name in ("2099-12-31 Stewardship.png", "9999-12-31 Dynamis.jpg", "Poster.png"):
            e = sched.entry_from_filename(name)
            self.assertIsNone(e["remove_after"], name)
            self.assertTrue(sched.is_active(e, TODAY), name)

    def test_last_day_is_still_active_and_next_day_is_not(self):
        e = {"show_from": None, "remove_after": "2026-12-01", "auto_archive": False}
        self.assertTrue(sched.is_active(e, date(2026, 12, 1)))
        self.assertFalse(sched.is_active(e, date(2026, 12, 2)))

    def test_start_date_hides_until_that_day(self):
        e = {"show_from": "2026-12-05", "remove_after": None, "auto_archive": False}
        self.assertFalse(sched.is_active(e, date(2026, 12, 4)))
        self.assertTrue(sched.is_active(e, date(2026, 12, 5)))
        self.assertEqual(sched.state_of(e, date(2026, 12, 4)), "scheduled")

    def test_sync_adds_new_files_and_prunes_missing_ones(self):
        self.touch("2026-12-01 A [auto-archive].png")
        self.touch("notes.txt")
        data = sched.sync(self.dir)
        self.assertEqual(list(data["images"]), ["2026-12-01 A [auto-archive].png"])
        (self.dir / "2026-12-01 A [auto-archive].png").unlink()
        self.assertEqual(sched.sync(self.dir)["images"], {})

    def test_set_entry_overrides_filename_and_keeps_name(self):
        self.touch("2026-12-01 A.png")
        sched.set_entry(self.dir, "2026-12-01 A.png", show_from="2026-11-20", remove_after="2026-12-10", auto_archive=True)
        entry = sched.sync(self.dir)["images"]["2026-12-01 A.png"]
        self.assertEqual((entry["show_from"], entry["remove_after"], entry["auto_archive"]), ("2026-11-20", "2026-12-10", True))
        self.assertTrue((self.dir / "2026-12-01 A.png").exists())

    def test_set_entry_validation(self):
        self.touch("A.png")
        with self.assertRaises(sched.ScheduleError):
            sched.set_entry(self.dir, "A.png", show_from="2026-12-10", remove_after="2026-12-01")
        with self.assertRaises(sched.ScheduleError):
            sched.set_entry(self.dir, "A.png", auto_archive=True)
        with self.assertRaises(sched.ScheduleError):
            sched.set_entry(self.dir, "../A.png")
        with self.assertRaises(sched.ScheduleError):
            sched.set_entry(self.dir, "missing.png")
        with self.assertRaises(sched.ScheduleError):
            sched.set_entry(self.dir, "A.png", remove_after="12/01/2026")

    def test_persistent_clears_dates_and_auto_archive(self):
        self.touch("A.png")
        e = sched.set_entry(self.dir, "A.png", show_from="2026-12-01", remove_after="2026-12-05", auto_archive=True, persistent=True)
        self.assertEqual((e["show_from"], e["remove_after"], e["auto_archive"]), (None, None, False))

    def test_sweep_archives_only_after_last_day_and_only_auto_archive(self):
        self.touch("2026-12-01 Keep.png")  # expires but not auto-archive
        self.touch("2026-12-01 Gone [auto-archive].png")
        self.touch("2026-12-02 Later [auto-archive].png")
        self.assertEqual(sched.sweep(self.dir, date(2026, 12, 1)), [])  # last day: still active
        self.assertEqual(sched.sweep(self.dir, date(2026, 12, 2)), ["2026-12-01 Gone [auto-archive].png"])
        self.assertTrue((self.dir / "archive" / "2026-12-01 Gone [auto-archive].png").exists())
        self.assertTrue((self.dir / "2026-12-01 Keep.png").exists())
        self.assertTrue((self.dir / "2026-12-02 Later [auto-archive].png").exists())
        self.assertNotIn("2026-12-01 Gone [auto-archive].png", sched.sync(self.dir)["images"])

    def test_sweep_never_overwrites_an_existing_archive_file(self):
        (self.dir / "archive").mkdir()
        (self.dir / "archive" / "2026-12-01 A [auto-archive].png").write_bytes(b"old")
        self.touch("2026-12-01 A [auto-archive].png")
        sched.sweep(self.dir, date(2026, 12, 3))
        self.assertEqual((self.dir / "archive" / "2026-12-01 A [auto-archive].png").read_bytes(), b"old")
        self.assertEqual(len(list((self.dir / "archive").iterdir())), 2)

    def test_active_names_hides_scheduled_and_expired(self):
        self.touch("2026-11-30 Expired.png")
        self.touch("Always.png")
        self.touch("Future.png")
        sched.set_entry(self.dir, "Future.png", show_from="2026-12-20")
        self.assertEqual(sched.active_names(self.dir, TODAY), {"Always.png"})

    def test_lock_held_env_skips_locking_without_deadlock(self):
        self.touch("A.png")
        os.environ["IMAGE_SCHEDULE_LOCK_HELD"] = "1"
        try:
            sched.sync(self.dir)
        finally:
            os.environ.pop("IMAGE_SCHEDULE_LOCK_HELD")

    def test_corrupt_schedule_file_is_rebuilt_from_names(self):
        self.touch("2026-12-01 A [auto-archive].png")
        (self.dir / sched.SCHEDULE_NAME).write_text("{not json")
        data = sched.sync(self.dir)
        self.assertTrue(data["images"]["2026-12-01 A [auto-archive].png"]["auto_archive"])

    def test_read_only_listing_writes_nothing(self):
        self.touch("2026-11-30 Old.png")
        rows = sched.listing(self.dir, TODAY, read_only=True)
        self.assertEqual([r["state"] for r in rows], ["expired"])
        self.assertFalse((self.dir / sched.SCHEDULE_NAME).exists())
        self.assertFalse((self.dir / sched.LOCK_NAME).exists())

    def test_cli_list_reports_states(self):
        self.touch("2026-11-30 Old.png")
        self.touch("Always.png")
        rc = sched.main(["--images-dir", str(self.dir), "--today", "2026-12-01", "sync"])
        self.assertEqual(rc, 0)
        rows = {r["filename"]: r["state"] for r in sched.listing(self.dir, TODAY)}
        self.assertEqual(rows, {"2026-11-30 Old.png": "expired", "Always.png": "persistent"})
        json.loads((self.dir / sched.SCHEDULE_NAME).read_text())


if __name__ == "__main__":
    unittest.main()
