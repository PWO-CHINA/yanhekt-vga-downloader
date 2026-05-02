import importlib.util
import json
import queue
import tempfile
import unittest
from collections import namedtuple
from unittest import mock
from pathlib import Path

import yanhekt_downloader as downloader
import yanhekt_gui


def load_installer_module():
    installer_path = Path(__file__).resolve().parent / "packaging" / "installer.py"
    spec = importlib.util.spec_from_file_location("yanhekt_packaging_installer", installer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load installer module from {installer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_managed_profile_dir_rejects_main_edge_profile(self) -> None:
        main_edge = Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data"
        self.assertFalse(downloader.is_managed_profile_dir(main_edge))

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

            with mock.patch.dict(downloader.os.environ, {"LOCALAPPDATA": str(Path(tmp) / "LocalAppData")}, clear=True), mock.patch.object(
                downloader,
                "http_json",
                return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:45678/devtools/browser/test"},
            ):
                self.assertEqual(downloader.discover_cdp_base(None, profile), "http://127.0.0.1:45678")

    def test_discover_cdp_base_ignores_and_cleans_stale_dedicated_profile_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "YanhektDownloader" / "chrome-profile"
            profile.mkdir(parents=True)
            port_file = profile / "DevToolsActivePort"
            port_file.write_text("45678\n/devtools/browser/test\n", encoding="utf-8")

            with mock.patch.dict(downloader.os.environ, {"LOCALAPPDATA": str(Path(tmp) / "LocalAppData")}, clear=True), mock.patch.object(
                downloader,
                "http_json",
                side_effect=TimeoutError("stale port"),
            ):
                self.assertEqual(downloader.discover_cdp_base(None, profile), downloader.DEFAULT_CDP)
                self.assertFalse(port_file.exists())

    def test_discover_cdp_base_does_not_scan_main_edge_profile_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp) / "LocalAppData"
            edge_profile = local_app_data / "Microsoft" / "Edge" / "User Data"
            edge_profile.mkdir(parents=True)
            (edge_profile / "DevToolsActivePort").write_text("56789\n/devtools/browser/edge\n", encoding="utf-8")

            with mock.patch.dict(downloader.os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True):
                self.assertEqual(downloader.discover_cdp_base(None, None), downloader.DEFAULT_CDP)

    def test_browser_ws_url_does_not_use_main_edge_devtools_port_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp) / "LocalAppData"
            edge_profile = local_app_data / "Microsoft" / "Edge" / "User Data"
            edge_profile.mkdir(parents=True)
            (edge_profile / "DevToolsActivePort").write_text("56789\n/devtools/browser/edge\n", encoding="utf-8")

            with mock.patch.dict(downloader.os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True), mock.patch.object(
                downloader,
                "http_json",
                side_effect=RuntimeError("no version endpoint"),
            ):
                with self.assertRaises(downloader.CdpError):
                    downloader.browser_ws_url("http://127.0.0.1:9222")

    def test_sanitize_filename_avoids_windows_reserved_names(self) -> None:
        self.assertEqual(downloader.sanitize_filename("CON.mp4"), "CON_file.mp4")
        self.assertEqual(downloader.sanitize_filename("aux"), "aux_file")

    def test_plan_filename_is_shortened_for_deep_output_dir(self) -> None:
        items = [
            {
                "course_name": "很长的课程名" * 20,
                "title": "很长的标题" * 40,
                "session_id": 1,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / ("deep" * 40)
            planned = downloader.build_download_plan(items, output_dir)

        self.assertLessEqual(len(str(planned[0][1])), downloader.MAX_WINDOWS_PATH_CHARS)

    def test_ensure_enough_free_space_raises_clear_error(self) -> None:
        usage = namedtuple("usage", "total used free")(10_000_000, 9_500_000, 500_000)
        with mock.patch.object(downloader.shutil, "disk_usage", return_value=usage):
            with self.assertRaises(downloader.InsufficientSpaceError):
                downloader.ensure_enough_free_space(Path("D:/Downloads"), 5_000_000)

    def test_ensure_writable_directory_rejects_too_deep_windows_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            too_deep = Path(tmp) / ("deep" * 80)
            with mock.patch.object(downloader.os, "name", "nt"):
                with self.assertRaisesRegex(OSError, "路径太深"):
                    downloader.ensure_writable_directory(too_deep)

    def test_with_playlist_query_appends_signed_params_to_segments(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok&Xclient_Signature=sig"

        self.assertEqual(
            downloader.with_playlist_query(playlist, "VGA0.ts"),
            "https://cvideo.yanhekt.cn/vod/x/VGA0.ts?Xvideo_Token=tok&Xclient_Signature=sig",
        )

    def test_with_playlist_query_preserves_existing_segment_query(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok&Xclient_Signature=sig"

        self.assertEqual(
            downloader.with_playlist_query(playlist, "VGA0.ts?part=1&Xvideo_Token=segment"),
            "https://cvideo.yanhekt.cn/vod/x/VGA0.ts?part=1&Xvideo_Token=segment&Xclient_Signature=sig",
        )

    def test_rewrite_playlist_text_materializes_signed_segment_urls(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok&Xclient_Signature=sig"
        text = "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\nVGA0.ts\n"

        rewritten, urls, resources = downloader.rewrite_playlist_text(playlist, text)

        self.assertIn(
            'URI="https://cvideo.yanhekt.cn/vod/x/key.bin?Xvideo_Token=tok&Xclient_Signature=sig"',
            rewritten,
        )
        self.assertIn(
            "https://cvideo.yanhekt.cn/vod/x/VGA0.ts?Xvideo_Token=tok&Xclient_Signature=sig",
            rewritten,
        )
        self.assertEqual(
            urls,
            ["https://cvideo.yanhekt.cn/vod/x/VGA0.ts?Xvideo_Token=tok&Xclient_Signature=sig"],
        )
        self.assertEqual(
            resources,
            ["https://cvideo.yanhekt.cn/vod/x/key.bin?Xvideo_Token=tok&Xclient_Signature=sig"],
        )

    def test_rewrite_playlist_text_rewrites_map_without_treating_it_as_segment(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok"
        text = '#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:10,\nVGA0.ts\n'

        rewritten, urls, resources = downloader.rewrite_playlist_text(playlist, text)

        self.assertIn('URI="https://cvideo.yanhekt.cn/vod/x/init.mp4?Xvideo_Token=tok"', rewritten)
        self.assertEqual(urls, ["https://cvideo.yanhekt.cn/vod/x/VGA0.ts?Xvideo_Token=tok"])
        self.assertEqual(resources, ["https://cvideo.yanhekt.cn/vod/x/init.mp4?Xvideo_Token=tok"])

    def test_choose_nested_playlist_prefers_video_variant(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/master.m3u8?Xvideo_Token=tok"
        text = (
            '#EXTM3U\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=256000,CODECS="mp4a.40.2"\n'
            'audio.m3u8\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"\n'
            'video720.m3u8\n'
        )
        urls = downloader.parse_playlist_urls(playlist, text)

        self.assertEqual(
            downloader.choose_nested_playlist(urls, text, playlist),
            "https://cvideo.yanhekt.cn/video720.m3u8?Xvideo_Token=tok",
        )

    def test_redact_media_urls_in_text_hides_signed_query_values(self) -> None:
        text = (
            "Error loading https://cvideo.yanhekt.cn/vod/x/VGA0.ts?"
            "Xvideo_Token=secret&Xclient_Signature=sig&part=1"
        )

        redacted = downloader.redact_media_urls_in_text(text)

        self.assertNotIn("secret", redacted)
        self.assertNotIn("sig", redacted)
        self.assertIn("Xvideo_Token=redacted", redacted)
        self.assertIn("part=1", redacted)

    def test_prepare_ffmpeg_hls_input_writes_rewritten_playlist(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok&Xclient_Signature=sig"

        def fake_read(url: str, referer: str) -> str:
            self.assertEqual(url, playlist)
            return "#EXTM3U\n#EXTINF:10,\nVGA0.ts\n"

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            downloader,
            "read_text_url",
            side_effect=fake_read,
        ), mock.patch.object(
            downloader,
            "fetch_bytes_range",
            return_value=(b"\x47" + b"\x00" * 187, "video/mp2t"),
        ) as fetch:
            path = downloader.prepare_ffmpeg_hls_input(playlist, "https://www.yanhekt.cn/session/1", Path(tmp))
            self.assertTrue(path.exists())
            self.assertIn("Xvideo_Token=tok", path.read_text(encoding="utf-8"))

        fetch.assert_called_once_with(
            "https://cvideo.yanhekt.cn/vod/x/VGA0.ts?Xvideo_Token=tok&Xclient_Signature=sig",
            "https://www.yanhekt.cn/session/1",
        )

    def test_prepare_ffmpeg_hls_input_rejects_html_segment(self) -> None:
        playlist = "https://cvideo.yanhekt.cn/vod/x/VGA.m3u8?Xvideo_Token=tok&Xclient_Signature=sig"

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            downloader,
            "read_text_url",
            return_value="#EXTM3U\nVGA0.ts\n",
        ), mock.patch.object(
            downloader,
            "fetch_bytes_range",
            return_value=(b"<html>login expired</html>", "text/html"),
        ):
            with self.assertRaises(downloader.MediaAccessError):
                downloader.prepare_ffmpeg_hls_input(playlist, "https://www.yanhekt.cn/session/1", Path(tmp))

    def test_estimate_hls_size_uses_selected_video_variant(self) -> None:
        master = "https://cvideo.yanhekt.cn/master.m3u8?Xvideo_Token=tok"
        video = "https://cvideo.yanhekt.cn/video720.m3u8?Xvideo_Token=tok"

        def fake_read(url: str, referer: str) -> str:
            if url == master:
                return (
                    '#EXTM3U\n'
                    '#EXT-X-STREAM-INF:BANDWIDTH=256000,CODECS="mp4a.40.2"\n'
                    'audio.m3u8\n'
                    '#EXT-X-STREAM-INF:BANDWIDTH=1200000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"\n'
                    'video720.m3u8\n'
                )
            self.assertEqual(url, video)
            return "#EXTM3U\n#EXTINF:10,\nVGA0.ts\n#EXTINF:10,\nVGA1.ts\n"

        with mock.patch.object(downloader, "read_text_url", side_effect=fake_read), mock.patch.object(
            downloader,
            "content_length",
            return_value=100,
        ) as length:
            estimated, segments = downloader.estimate_hls_size(master, "https://www.yanhekt.cn/session/1")

        self.assertEqual(estimated, 200)
        self.assertEqual(segments, 2)
        length.assert_any_call("https://cvideo.yanhekt.cn/VGA0.ts?Xvideo_Token=tok", "https://www.yanhekt.cn/session/1")

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
        self.assertIn("--test-type", args)
        self.assertIn("--disable-infobars", args)
        self.assertEqual(args[-1], "https://www.yanhekt.cn/course/12345")

    def test_find_ffmpeg_prefers_bundled_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ffmpeg = root / "ffmpeg.exe"
            ffmpeg.write_text("fake", encoding="utf-8")
            with mock.patch.object(downloader, "resource_dirs", return_value=[root]):
                self.assertEqual(downloader.find_ffmpeg(None), str(ffmpeg))

    def test_find_ffmpeg_accepts_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ffmpeg = Path(tmp) / "ffmpeg.exe"
            ffmpeg.write_text("fake", encoding="utf-8")
            self.assertEqual(downloader.find_ffmpeg(str(ffmpeg)), str(ffmpeg))

    def test_find_ffmpeg_rejects_missing_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "ffmpeg not found at"):
                downloader.find_ffmpeg(str(Path(tmp) / "missing.exe"))

    def test_find_browser_prefers_chrome_when_both_are_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chrome = root / "ProgramFiles" / "Google" / "Chrome" / "Application" / "chrome.exe"
            edge = root / "ProgramFilesX86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            chrome.parent.mkdir(parents=True)
            edge.parent.mkdir(parents=True)
            chrome.write_text("chrome", encoding="utf-8")
            edge.write_text("edge", encoding="utf-8")
            env = {
                "PROGRAMFILES": str(root / "ProgramFiles"),
                "PROGRAMFILES(X86)": str(root / "ProgramFilesX86"),
                "LOCALAPPDATA": str(root / "LocalAppData"),
            }

            with mock.patch.dict(downloader.os.environ, env, clear=True), mock.patch.object(
                downloader.shutil,
                "which",
                return_value=None,
            ):
                self.assertEqual(downloader.find_browser(None), str(chrome))

    def test_find_browser_falls_back_to_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edge = root / "ProgramFilesX86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            edge.parent.mkdir(parents=True)
            edge.write_text("edge", encoding="utf-8")
            env = {
                "PROGRAMFILES": str(root / "ProgramFiles"),
                "PROGRAMFILES(X86)": str(root / "ProgramFilesX86"),
                "LOCALAPPDATA": str(root / "LocalAppData"),
            }

            with mock.patch.dict(downloader.os.environ, env, clear=True), mock.patch.object(
                downloader.shutil,
                "which",
                return_value=None,
            ):
                self.assertEqual(downloader.find_browser(None), str(edge))

    def test_find_browser_accepts_explicit_path(self) -> None:
        self.assertEqual(downloader.find_browser("C:/tools/msedge.exe"), str(Path("C:/tools/msedge.exe")))

    def test_find_browser_error_mentions_chrome_and_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "PROGRAMFILES": str(root / "ProgramFiles"),
                "PROGRAMFILES(X86)": str(root / "ProgramFilesX86"),
                "LOCALAPPDATA": str(root / "LocalAppData"),
            }
            with mock.patch.dict(downloader.os.environ, env, clear=True), mock.patch.object(
                downloader.shutil,
                "which",
                return_value=None,
            ):
                with self.assertRaisesRegex(FileNotFoundError, "Chrome or Microsoft Edge"):
                    downloader.find_browser(None)

    def test_parse_args_keeps_legacy_chrome_option_as_browser_path(self) -> None:
        with mock.patch.object(
            downloader.sys,
            "argv",
            ["yanhekt_downloader.py", "12345", "--chrome", "C:/tools/msedge.exe"],
        ):
            self.assertEqual(downloader.parse_args().browser, "C:/tools/msedge.exe")

    def test_parse_args_accepts_browser_option(self) -> None:
        with mock.patch.object(
            downloader.sys,
            "argv",
            ["yanhekt_downloader.py", "12345", "--browser", "C:/tools/msedge.exe"],
        ):
            self.assertEqual(downloader.parse_args().browser, "C:/tools/msedge.exe")

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

    def test_gui_frozen_missing_worker_reports_incomplete_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(yanhekt_gui, "SCRIPT_DIR", root), mock.patch.object(
                yanhekt_gui.sys,
                "frozen",
                True,
                create=True,
            ):
                with self.assertRaisesRegex(FileNotFoundError, "安装不完整"):
                    yanhekt_gui.downloader_command_base()

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

    def test_plan_json_line_is_ascii_safe(self) -> None:
        payload = {
            "course_name": "生物仪器分析(本科课程)",
            "items": [{"title": "第1周 星期二 第4大节", "filename": "生物仪器分析_课堂录屏.mp4"}],
        }

        line = downloader.plan_json_line(payload)

        self.assertTrue(line.isascii())
        self.assertTrue(line.startswith(downloader.PLAN_JSON_PREFIX))
        decoded = json.loads(line[len(downloader.PLAN_JSON_PREFIX):])
        self.assertEqual(decoded, payload)


class InstallerTests(unittest.TestCase):
    def test_create_desktop_shortcut_uses_resolved_desktop_and_verifies_file(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_dir = root / "Install Dir"
            install_dir.mkdir()
            icon_file = install_dir / installer.APP_ICON_NAME
            icon_file.write_text("icon", encoding="utf-8")
            desktop = root / "Redirected Desktop"
            legacy_shortcut = desktop / "Yanhekt Downloader.lnk"
            legacy_shortcut.parent.mkdir(parents=True)
            legacy_shortcut.write_text("legacy", encoding="utf-8")
            current_shortcut = desktop / f"{installer.APP_NAME}.lnk"
            current_shortcut.write_text("old target", encoding="utf-8")
            logs: list[str] = []

            def fake_save(target: Path, shortcut: Path, working_dir: Path, description: str, icon: str) -> None:
                self.assertEqual(target, install_dir / installer.EXE_NAME)
                self.assertEqual(shortcut, desktop / f"{installer.APP_NAME}.lnk")
                self.assertEqual(working_dir, install_dir)
                self.assertEqual(description, installer.APP_NAME)
                self.assertEqual(icon, str(icon_file))
                self.assertFalse(shortcut.exists())
                shortcut.write_text("shortcut", encoding="utf-8")

            with mock.patch.object(installer, "desktop_path", return_value=desktop), mock.patch.object(
                installer,
                "save_shell_shortcut",
                side_effect=fake_save,
            ):
                self.assertTrue(installer.create_desktop_shortcut(install_dir, logs.append))

            self.assertTrue((desktop / f"{installer.APP_NAME}.lnk").exists())
            self.assertFalse(legacy_shortcut.exists())
            self.assertIn("已创建桌面快捷方式", logs[-1])

    def test_create_desktop_shortcut_fails_if_lnk_was_not_created(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_dir = root / "Install"
            install_dir.mkdir()
            desktop = root / "Desktop"
            logs: list[str] = []
            with mock.patch.object(installer, "desktop_path", return_value=desktop), mock.patch.object(
                installer,
                "save_shell_shortcut",
                return_value=None,
            ):
                self.assertFalse(installer.create_desktop_shortcut(install_dir, logs.append))

            self.assertIn("桌面快捷方式创建失败", logs[-1])

    def test_validate_installation_requires_worker_and_runtime_files(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            for name in installer.REQUIRED_PAYLOAD_FILES:
                if name != installer.WORKER_EXE_NAME:
                    (install_dir / name).write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, installer.WORKER_EXE_NAME):
                installer.validate_installation(install_dir)

    def test_install_returns_warning_when_shortcut_fails(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "Install"
            logs: list[str] = []
            with mock.patch.object(installer, "check_free_space"), mock.patch.object(
                installer,
                "extract_payload",
                side_effect=lambda target, log: target.mkdir(parents=True, exist_ok=True),
            ), mock.patch.object(installer, "validate_installation"), mock.patch.object(
                installer,
                "create_desktop_shortcut",
                return_value=False,
            ):
                warnings = installer.install(install_dir, shortcut=True, launch=False, log=logs.append)

            self.assertEqual(len(warnings), 1)
            self.assertIn("桌面快捷方式创建失败", warnings[0])

    def test_install_checks_for_running_app_before_extract(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "Install"
            logs: list[str] = []
            with mock.patch.object(installer, "check_free_space"), mock.patch.object(
                installer,
                "ensure_writable_install_dir",
            ), mock.patch.object(
                installer,
                "ensure_app_not_running",
                side_effect=RuntimeError("still running"),
            ), mock.patch.object(
                installer,
                "extract_payload",
            ) as extract:
                with self.assertRaisesRegex(RuntimeError, "still running"):
                    installer.install(install_dir, shortcut=False, launch=False, log=logs.append)

            extract.assert_not_called()

    def test_launch_app_missing_exe_is_explicit_error(self) -> None:
        installer = load_installer_module()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "找不到主程序"):
                installer.launch_app(Path(tmp))


class GuiCompletionTests(unittest.TestCase):
    class FakeVar:
        def __init__(self) -> None:
            self.value = None

        def set(self, value: object) -> None:
            self.value = value

    class FakeRoot:
        def __init__(self) -> None:
            self.scheduled: list[tuple[int, object]] = []

        def after(self, delay_ms: int, callback: object) -> None:
            self.scheduled.append((delay_ms, callback))

        def destroy(self) -> None:
            pass

    class FakeProgress:
        def __init__(self) -> None:
            self.started = False
            self.options: dict[str, object] = {}

        def start(self, interval: int) -> None:
            self.started = True
            self.options["interval"] = interval

        def stop(self) -> None:
            self.started = False

        def configure(self, **kwargs: object) -> None:
            self.options.update(kwargs)

    def poll_done(self, mode: str, code: int):
        gui = yanhekt_gui.YanhektGui.__new__(yanhekt_gui.YanhektGui)
        gui.events = queue.Queue()
        gui.events.put(("done", code))
        gui.process = mock.Mock()
        gui.process_mode = mode
        gui.plan_items = []
        gui.progress_var = self.FakeVar()
        gui.status_var = self.FakeVar()
        gui.root = self.FakeRoot()
        gui.progress = self.FakeProgress()
        gui.set_running = mock.Mock()
        gui.append_log = mock.Mock()
        gui.recent_lines = []
        gui.error_dialog_shown = False

        with mock.patch.object(yanhekt_gui.messagebox, "showerror"):
            yanhekt_gui.YanhektGui.poll_events(gui)
        return gui

    def has_destroy_callback(self, gui: yanhekt_gui.YanhektGui) -> bool:
        return any(
            delay == yanhekt_gui.AUTO_EXIT_DELAY_MS and getattr(callback, "__name__", "") == "destroy"
            for delay, callback in gui.root.scheduled
        )

    def test_download_success_schedules_auto_exit(self) -> None:
        gui = self.poll_done("download", 0)

        self.assertEqual(gui.progress_var.value, 100.0)
        self.assertEqual(gui.status_var.value, "下载完成，程序即将退出")
        self.assertTrue(self.has_destroy_callback(gui))

    def test_plan_success_does_not_auto_exit(self) -> None:
        gui = self.poll_done("plan", 0)

        self.assertFalse(self.has_destroy_callback(gui))

    def test_download_failure_does_not_auto_exit(self) -> None:
        gui = self.poll_done("download", 2)

        self.assertEqual(gui.status_var.value, "已退出，代码 2")
        self.assertFalse(self.has_destroy_callback(gui))


class ProcessCleanupTests(unittest.TestCase):
    class FakeProcess:
        pid = 12345

        def __init__(self) -> None:
            self.waited = False
            self.terminated = False
            self.killed = False
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            self.waited = True
            self.returncode = 0
            return 0

        def kill(self) -> None:
            self.killed = True
            self.returncode = -9

    def test_terminate_process_waits_for_process_exit(self) -> None:
        proc = self.FakeProcess()
        with mock.patch.object(downloader.subprocess, "run") as run:
            downloader.terminate_process(proc)

        self.assertTrue(proc.waited)
        if downloader.os.name == "nt":
            run.assert_called_once()
            self.assertFalse(proc.terminated)
        else:
            self.assertTrue(proc.terminated)


if __name__ == "__main__":
    unittest.main()
