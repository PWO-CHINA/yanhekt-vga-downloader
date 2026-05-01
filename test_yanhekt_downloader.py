import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yanhekt_downloader as downloader
import yanhekt_gui


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64 + b"moov"


class FilenameTests(unittest.TestCase):
    def test_filename_includes_course_name_when_available(self) -> None:
        item = {
            "started_at": "2026-05-01 19:30:00",
            "course_name": "生物仪器分析(本科课程)",
            "title": "第1周 星期二 第4大节",
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertEqual(name, "生物仪器分析(本科课程)_第1周_星期二_第4大节_课堂录屏.mp4")

    def test_filename_uses_title_only_without_course_name(self) -> None:
        item = {
            "started_at": "2026-05-01 19:30:00",
            "title": "第1周 星期二 第4大节",
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertEqual(name, "第1周_星期二_第4大节_课堂录屏.mp4")

    def test_long_title_preserves_vga_mp4_suffix(self) -> None:
        item = {
            "started_at": "2026-05-01 19:30:00",
            "course_name": "很长的课程名" * 50,
            "title": "课程" * 200,
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertLessEqual(len(name), 180)
        self.assertTrue(name.endswith("_课堂录屏.mp4"))

    def test_filename_sanitizes_course_name(self) -> None:
        item = {
            "course_name": "生物/仪器:分析*本科?",
            "title": "第1周 星期二 第4大节",
            "session_id": 858571,
        }

        name = downloader.filename_for(item, 1)

        self.assertEqual(name, "生物_仪器_分析_本科_第1周_星期二_第4大节_课堂录屏.mp4")

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
            target = output_dir / "good_name_课堂录屏.mp4"
            legacy.write_bytes(fake_mp4())

            renamed = downloader.repair_legacy_mp_extensions(output_dir, [target])

            self.assertEqual([(old.name, new.name) for old, new in renamed], [(".mp_", target.name)])
            self.assertTrue(target.exists())

    def test_repair_legacy_vga_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            old_name = output_dir / "01_same_session-1_VGA.mp4"
            old_name.write_bytes(fake_mp4())

            renamed = downloader.repair_legacy_mp_extensions(output_dir)

            self.assertEqual(
                [(old.name, new.name) for old, new in renamed],
                [("01_same_session-1_VGA.mp4", "01_same_session-1_课堂录屏.mp4")],
            )
            self.assertFalse(old_name.exists())
            self.assertTrue((output_dir / "01_same_session-1_课堂录屏.mp4").exists())

    def test_repair_legacy_long_recording_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            old_name = output_dir / "01_2026-03-03_1515_第1周 星期二 第4大节_session-829412_课堂录屏.mp4"
            old_name.write_bytes(fake_mp4())

            renamed = downloader.repair_legacy_mp_extensions(output_dir)

            self.assertEqual(
                [(old.name, new.name) for old, new in renamed],
                [("01_2026-03-03_1515_第1周 星期二 第4大节_session-829412_课堂录屏.mp4", "第1周_星期二_第4大节_课堂录屏.mp4")],
            )
            self.assertFalse(old_name.exists())
            self.assertTrue((output_dir / "第1周_星期二_第4大节_课堂录屏.mp4").exists())

    def test_planned_names_are_distinct(self) -> None:
        items = [
            {"started_at": "", "course_name": "course", "title": "same", "session_id": 1},
            {"started_at": "", "course_name": "course", "title": "same", "session_id": 1},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            planned = downloader.build_download_plan(items, Path(tmp))

        self.assertNotEqual(planned[0][1].name, planned[1][1].name)
        self.assertEqual(planned[0][1].name, "course_same_课堂录屏.mp4")
        self.assertEqual(planned[1][1].name, "course_same_课堂录屏 (2).mp4")

    def test_parse_duration_accepts_colon_formats(self) -> None:
        self.assertEqual(downloader.parse_duration("01:02"), 62)
        self.assertEqual(downloader.parse_duration("01:02:03"), 3723)

    def test_filter_plan_by_session_ids_keeps_planned_filename(self) -> None:
        items = [
            {"started_at": "", "course_name": "course", "title": "first", "session_id": 1},
            {"started_at": "", "course_name": "course", "title": "second", "session_id": 2},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            planned = downloader.build_download_plan(items, Path(tmp))
            selected = downloader.filter_plan_by_session_ids(planned, {"2"})

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][1].name, "course_second_课堂录屏.mp4")

    def test_parse_session_ids_accepts_common_separators(self) -> None:
        self.assertEqual(downloader.parse_session_ids("1, 2;3  4"), {"1", "2", "3", "4"})

    def test_managed_profile_dir_accepts_default_profile(self) -> None:
        self.assertTrue(downloader.is_managed_profile_dir(downloader.default_profile_dir()))

    def test_managed_profile_dir_rejects_main_chrome_profile(self) -> None:
        main_chrome = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
        self.assertFalse(downloader.is_managed_profile_dir(main_chrome))

    def test_managed_profile_dir_accepts_named_tool_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "YanhektDownloader" / "chrome-profile"
            with mock.patch.object(downloader, "default_profile_dir", return_value=Path(tmp) / "default"):
                self.assertTrue(downloader.is_managed_profile_dir(profile))

    def test_discover_cdp_base_prefers_dedicated_profile_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "YanhektDownloader" / "chrome-profile"
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text("45678\n/devtools/browser/test\n", encoding="utf-8")

            with mock.patch.dict(downloader.os.environ, {"LOCALAPPDATA": str(Path(tmp) / "LocalAppData")}, clear=True):
                self.assertEqual(downloader.discover_cdp_base(None, profile), "http://127.0.0.1:45678")

    def test_chrome_launch_args_can_run_headless(self) -> None:
        args = downloader.chrome_launch_args(
            "chrome.exe",
            Path("profile"),
            "https://www.yanhekt.cn/course/12345",
            headless=True,
        )

        self.assertIn("--headless=new", args)
        self.assertIn("--disable-gpu", args)
        self.assertEqual(args[-1], "https://www.yanhekt.cn/course/12345")

    def test_chrome_launch_args_visible_by_default(self) -> None:
        args = downloader.chrome_launch_args(
            "chrome.exe",
            Path("profile"),
            "https://www.yanhekt.cn/course/12345",
        )

        self.assertNotIn("--headless=new", args)
        self.assertEqual(args[-1], "https://www.yanhekt.cn/course/12345")

    def test_find_ffmpeg_prefers_bundled_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ffmpeg = root / "ffmpeg.exe"
            ffmpeg.write_text("fake", encoding="utf-8")
            with mock.patch.object(downloader, "resource_dirs", return_value=[root]):
                self.assertEqual(downloader.find_ffmpeg(None), str(ffmpeg))

    def test_find_ffmpeg_accepts_explicit_path(self) -> None:
        self.assertEqual(downloader.find_ffmpeg("C:/tools/ffmpeg.exe"), str(Path("C:/tools/ffmpeg.exe")))

    def test_gui_uses_worker_exe_when_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = root / "YanhektDownloaderWorker.exe"
            worker.write_text("fake", encoding="utf-8")
            with mock.patch.object(yanhekt_gui, "SCRIPT_DIR", root), mock.patch.object(
                yanhekt_gui.sys,
                "frozen",
                True,
                create=True,
            ):
                self.assertEqual(yanhekt_gui.downloader_command_base(), [str(worker)])

    def test_gui_uses_python_script_in_source_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(yanhekt_gui, "SCRIPT_DIR", root), mock.patch.object(
                yanhekt_gui.sys,
                "frozen",
                False,
                create=True,
            ):
                self.assertEqual(
                    yanhekt_gui.downloader_command_base(),
                    [yanhekt_gui.sys.executable, str(root / "yanhekt_downloader.py")],
                )


if __name__ == "__main__":
    unittest.main()
