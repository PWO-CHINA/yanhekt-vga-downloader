import tempfile
import unittest
from pathlib import Path

import yanhekt_downloader as downloader


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64 + b"moov"


class FilenameTests(unittest.TestCase):
    def test_filename_keeps_digits_date_and_mp4_extension(self) -> None:
        item = {
            "started_at": "2026-05-01 19:30:00",
            "title": "第1节 课程: A/B?",
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertTrue(name.endswith("_VGA.mp4"))
        self.assertIn("01_2026-05-01_1930_", name)
        self.assertIn("session-858571", name)
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)

    def test_long_title_preserves_vga_mp4_suffix(self) -> None:
        item = {
            "started_at": "2026-05-01 19:30:00",
            "title": "课程" * 200,
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertLessEqual(len(name), 180)
        self.assertTrue(name.endswith("_VGA.mp4"))

    def test_repair_legacy_mp_extension_skips_part_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            complete = output_dir / "lesson.mp_"
            partial = output_dir / "lesson2.mp_.part"
            complete.write_bytes(fake_mp4())
            partial.write_bytes(b"partial-data")

            renamed = downloader.repair_legacy_mp_extensions(output_dir)

            self.assertEqual([(old.name, new.name) for old, new in renamed], [("lesson.mp_", "lesson.mp4")])
            self.assertFalse(complete.exists())
            self.assertTrue((output_dir / "lesson.mp4").exists())
            self.assertTrue(partial.exists())

    def test_repair_legacy_mp_extension_skips_invalid_mp4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            broken = output_dir / "broken.mp_"
            broken.write_bytes(b"not-a-complete-mp4")

            renamed = downloader.repair_legacy_mp_extensions(output_dir)

            self.assertEqual(renamed, [])
            self.assertTrue(broken.exists())

    def test_repair_legacy_mp_extension_can_use_planned_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            legacy = output_dir / ".mp_"
            target = output_dir / "01_good_name_session-1_VGA.mp4"
            legacy.write_bytes(fake_mp4())

            renamed = downloader.repair_legacy_mp_extensions(output_dir, [target])

            self.assertEqual([(old.name, new.name) for old, new in renamed], [(".mp_", target.name)])
            self.assertTrue(target.exists())

    def test_planned_names_are_distinct(self) -> None:
        items = [
            {"started_at": "", "title": "same", "session_id": 1},
            {"started_at": "", "title": "same", "session_id": 1},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            planned = downloader.build_download_plan(items, Path(tmp))

        self.assertNotEqual(planned[0][1].name, planned[1][1].name)
        self.assertEqual(planned[0][1].name, "01_same_session-1_VGA.mp4")
        self.assertEqual(planned[1][1].name, "02_same_session-1_VGA.mp4")

    def test_parse_duration_accepts_colon_formats(self) -> None:
        self.assertEqual(downloader.parse_duration("01:02"), 62)
        self.assertEqual(downloader.parse_duration("01:02:03"), 3723)


if __name__ == "__main__":
    unittest.main()
