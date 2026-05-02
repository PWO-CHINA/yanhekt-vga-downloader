#!/usr/bin/env python3
"""Build the v0.0.x Windows installer for the yanhekt/延河课堂 downloader."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / "VERSION"
BUILD_DIR = REPO / "build" / "release"
DIST_DIR = REPO / "dist"
RELEASE_DIR = REPO / "release"
META_DIR = BUILD_DIR / "meta"
PAYLOAD_DIR = BUILD_DIR / "payload"
PAYLOAD_ZIP = BUILD_DIR / "release_payload.zip"
APP_EXE = "YanhektDownloader.exe"
WORKER_EXE = "YanhektDownloaderWorker.exe"
APP_ICON = "yanhekt_downloader.ico"
SETUP_NAME_TEMPLATE = "YanhektDownloader_Setup_v{version}.exe"


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def assert_under_repo(path: Path) -> None:
    resolved = path.resolve()
    repo = REPO.resolve()
    if resolved != repo and repo not in resolved.parents:
        raise RuntimeError(f"Refusing to touch path outside repo: {resolved}")


def clean_dir(path: Path) -> None:
    assert_under_repo(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError(f"VERSION must use SemVer MAJOR.MINOR.PATCH, got: {version!r}")
    return version


def version_tuple(version: str) -> tuple[int, int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch, 0


def ensure_build_dependency(module: str, package: str) -> None:
    try:
        __import__(module)
        return
    except ImportError:
        pass
    log(f"Installing build dependency: {package}")
    subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)


def generate_icon(icon_path: Path) -> None:
    ensure_build_dependency("PIL", "pillow")
    from PIL import Image, ImageDraw

    icon_path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images: list[Image.Image] = []
    for size in sizes:
        canvas_size = size * 4
        scale = canvas_size / 256
        image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        def point(x: int, y: int) -> tuple[int, int]:
            return round(x * scale), round(y * scale)

        def box(coords: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
            left, top, right, bottom = coords
            return round(left * scale), round(top * scale), round(right * scale), round(bottom * scale)

        draw.rounded_rectangle(box((18, 18, 238, 238)), radius=max(8, round(44 * scale)), fill="#111827")
        draw.rounded_rectangle(box((32, 32, 224, 224)), radius=max(6, round(34 * scale)), fill="#2563eb")
        draw.polygon([point(86, 66), point(178, 128), point(86, 190)], fill="#ffffff")
        draw.rounded_rectangle(box((74, 188, 182, 206)), radius=max(2, round(8 * scale)), fill="#34d399")
        if size >= 32:
            draw.polygon([point(128, 82), point(186, 128), point(128, 174)], fill="#34d399")
            draw.rounded_rectangle(box((58, 52, 78, 204)), radius=max(2, round(8 * scale)), fill="#ffffff")
        if size >= 64:
            draw.line([point(154, 156), point(192, 156)], fill="#ffffff", width=max(5, round(10 * scale)))
            draw.polygon([point(198, 156), point(174, 138), point(174, 174)], fill="#ffffff")

        resample = getattr(Image, "Resampling", Image).LANCZOS
        images.append(image.resize((size, size), resample))
    images[-1].save(icon_path, sizes=[(size, size) for size in sizes], append_images=images[:-1])
    log(f"Generated icon: {icon_path}")


def write_version_file(path: Path, version: str, description: str, original_filename: str) -> None:
    filevers = version_tuple(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'PWO-CHINA'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026 PWO-CHINA'),
        StringStruct('OriginalFilename', '{original_filename}'),
        StringStruct('ProductName', 'yanhekt/延河课堂录屏下载器'),
        StringStruct('ProductVersion', '{version}')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def run_pyinstaller(args: list[str]) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(BUILD_DIR / "pyinstaller"),
        "--specpath",
        str(BUILD_DIR / "specs"),
        "--distpath",
        str(DIST_DIR),
    ] + args
    log("Running: " + " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=str(REPO), check=True)


def find_ffmpeg() -> Path:
    bundled = sorted(REPO.glob("ffmpeg-*full_build/bin/ffmpeg.exe"))
    if bundled:
        return bundled[-1]
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise RuntimeError("Could not find ffmpeg.exe. Put ffmpeg in PATH or under ffmpeg-*full_build/bin/.")


def copy_payload_files() -> None:
    clean_dir(PAYLOAD_DIR)
    for filename in [APP_EXE, WORKER_EXE]:
        source = DIST_DIR / filename
        if not source.exists():
            raise RuntimeError(f"Missing built executable: {source}")
        shutil.copy2(source, PAYLOAD_DIR / filename)
    for filename in ["README.md", "LICENSE", "VERSION"]:
        shutil.copy2(REPO / filename, PAYLOAD_DIR / filename)
    shutil.copy2(META_DIR / APP_ICON, PAYLOAD_DIR / APP_ICON)
    shutil.copy2(find_ffmpeg(), PAYLOAD_DIR / "ffmpeg.exe")
    log(f"Assembled installer payload: {PAYLOAD_DIR}")


def zip_payload() -> None:
    if PAYLOAD_ZIP.exists():
        PAYLOAD_ZIP.unlink()
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PAYLOAD_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(PAYLOAD_DIR).as_posix())
    log(f"Created payload zip: {PAYLOAD_ZIP}")


def build(version: str) -> Path:
    ensure_build_dependency("PyInstaller", "pyinstaller")
    clean_dir(BUILD_DIR)
    clean_dir(DIST_DIR)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    icon = META_DIR / APP_ICON
    generate_icon(icon)
    gui_version = META_DIR / "version_gui.txt"
    worker_version = META_DIR / "version_worker.txt"
    setup_version = META_DIR / "version_setup.txt"
    write_version_file(gui_version, version, "yanhekt/延河课堂 classroom recording downloader", APP_EXE)
    write_version_file(worker_version, version, "yanhekt/延河课堂 downloader background worker", WORKER_EXE)
    write_version_file(setup_version, version, "yanhekt/延河课堂 downloader installer", SETUP_NAME_TEMPLATE.format(version=version))

    run_pyinstaller(
        [
            "--onefile",
            "--noconsole",
            f"--icon={icon}",
            f"--version-file={gui_version}",
            "--name",
            "YanhektDownloader",
            "yanhekt_gui.py",
        ]
    )
    run_pyinstaller(
        [
            "--onefile",
            f"--icon={icon}",
            f"--version-file={worker_version}",
            "--name",
            "YanhektDownloaderWorker",
            "yanhekt_downloader.py",
        ]
    )

    copy_payload_files()
    zip_payload()
    setup_name = SETUP_NAME_TEMPLATE.format(version=version)
    run_pyinstaller(
        [
            "--onefile",
            "--noconsole",
            f"--icon={icon}",
            f"--version-file={setup_version}",
            "--add-data",
            f"{PAYLOAD_ZIP};.",
            "--name",
            setup_name[:-4],
            "packaging/installer.py",
        ]
    )
    setup_source = DIST_DIR / setup_name
    setup_target = RELEASE_DIR / setup_name
    if not setup_source.exists():
        raise RuntimeError(f"Missing installer executable: {setup_source}")
    shutil.copy2(setup_source, setup_target)
    log(f"Release installer: {setup_target}")
    return setup_target


def main() -> int:
    os.chdir(REPO)
    version = read_version()
    setup = build(version)
    print()
    print("=" * 60)
    print(f"Built yanhekt/延河课堂 downloader v{version}")
    print(f"Installer: {setup}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
