import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server


class BrandingAndVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.multiple(
            server,
            APP_DIR=str(self.dir),
            VERSION_RECORD=str(self.dir / "installed-version.json"),
            DEFAULT_DISPLAY_DAYS=10,
            MAX_DISPLAY_DAYS=10,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.configured = self.dir / "images"
        folder_patch = mock.patch.object(server.image_schedule, "resolve_images_dir", side_effect=lambda explicit: self.configured)
        folder_patch.start()
        self.addCleanup(folder_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_config(self, data):
        (self.dir / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def test_defaults_without_config(self):
        self.assertEqual(
            server.get_branding(),
            {
                "title": "Church Calendar",
                "subtitle": "Upcoming Events \u2022 Next 10 Days",
                "subtitle_template": "Upcoming Events \u2022 Next {days} Days",
                "default_days": 10,
                "max_days": 10,
                "page_title": "Church Calendar - Calendar",
            },
        )

    def test_branding_reports_default_and_maximum_days(self):
        with mock.patch.multiple(server, DEFAULT_DISPLAY_DAYS=7, MAX_DISPLAY_DAYS=21):
            b = server.get_branding()
        self.assertEqual((b["default_days"], b["max_days"]), (7, 21))
        self.assertEqual(b["subtitle"], "Upcoming Events \u2022 Next 7 Days")

    def test_day_limits(self):
        self.assertEqual(server.resolve_day_limits(90, 10, 0), (10, 10))
        self.assertEqual(server.resolve_day_limits(90, 10, 30), (10, 30))
        self.assertEqual(server.resolve_day_limits(90, 10, 5), (5, 5))
        self.assertEqual(server.resolve_day_limits(14, 10, 60), (10, 14))
        self.assertEqual(server.resolve_day_limits(7, 10, 0), (7, 7))

    def test_configured_text_and_placeholders(self):
        self.write_config({"branding": {"title": "Parish Hall", "subtitle": "Coming up in {days} days"}})
        b = server.get_branding()
        self.assertEqual(b["title"], "Parish Hall")
        self.assertEqual(b["subtitle"], "Coming up in 10 days")
        self.assertEqual(b["page_title"], "Parish Hall - Calendar")

    def test_custom_page_title_can_use_title(self):
        self.write_config({"branding": {"title": "Parish Hall", "page_title": "{title} Events"}})
        self.assertEqual(server.get_branding()["page_title"], "Parish Hall Events")

    def test_blank_or_non_string_values_fall_back_and_length_is_capped(self):
        self.write_config({"branding": {"title": "   ", "subtitle": 5, "page_title": "x" * 500}})
        b = server.get_branding()
        self.assertEqual(b["title"], "Church Calendar")
        self.assertEqual(b["subtitle"], "Upcoming Events \u2022 Next 10 Days")
        self.assertEqual(len(b["page_title"]), 120)

    def test_malformed_branding_section_falls_back(self):
        self.write_config({"branding": "nope"})
        self.assertEqual(server.get_branding()["title"], "Church Calendar")

    def test_version_prefers_installed_record(self):
        (self.dir / "installed-version.json").write_text(json.dumps({"version": "1.1.0", "tag": "v1.1.0-rc.4"}))
        (self.dir / "VERSION").write_text("9.9.9\n")
        self.assertEqual(server.get_version_info(), {"version": "1.1.0", "tag": "v1.1.0-rc.4"})

    def test_version_falls_back_to_version_file_then_none(self):
        self.assertEqual(server.get_version_info(), {"version": None, "tag": None})
        (self.dir / "VERSION").write_text("1.1.0\n")
        self.assertEqual(server.get_version_info(), {"version": "1.1.0", "tag": None})

    def test_preview_prefers_optimized_then_thumbnail_then_original(self):
        name = "2026-12-20 Sale [auto-archive].png"
        quoted = "2026-12-20%20Sale%20%5Bauto-archive%5D.png"
        self.assertEqual(server.image_preview_url(name), f"/images/{quoted}")
        (self.dir / "images" / "thumbnails").mkdir(parents=True)
        (self.dir / "images" / "thumbnails" / (name + ".webp")).write_bytes(b"x")
        self.assertEqual(server.image_preview_url(name), f"/thumbnails/{quoted}.webp")
        (self.dir / "images" / "optimized").mkdir()
        (self.dir / "images" / "optimized" / (name + ".webp")).write_bytes(b"x")
        self.assertEqual(server.image_preview_url(name), f"/optimized/{quoted}.webp")

    def test_originals_in_an_external_folder_are_served_by_the_source_route(self):
        self.configured = self.dir / "mnt-posters"
        self.configured.mkdir()
        self.assertEqual(server.image_preview_url("a b.png"), "/source-images/a%20b.png")
        (self.dir / "images" / "optimized").mkdir(parents=True)
        (self.dir / "images" / "optimized" / "a b.png.webp").write_bytes(b"x")
        self.assertEqual(server.image_preview_url("a b.png"), "/optimized/a%20b.png.webp")

    def test_source_route_only_serves_bare_image_names_from_the_configured_folder(self):
        self.configured = self.dir / "mnt-posters"
        self.configured.mkdir()
        (self.configured / "ok.png").write_bytes(b"x")
        (self.configured / "notes.txt").write_text("secret")
        (self.dir / "config.json").write_text("{}")
        self.assertEqual(server.resolve_source_image("ok.png"), self.configured / "ok.png")
        for bad in ("../config.json", "sub/ok.png", "notes.txt", "missing.png", "", ".."):
            self.assertIsNone(server.resolve_source_image(bad), bad)


if __name__ == "__main__":
    unittest.main()
