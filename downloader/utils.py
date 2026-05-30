from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from .config import get_config_dir


EXTRA_TOOL_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/opt/local/bin",
]


def ensure_tool_path() -> None:
    """Make GUI-launched macOS apps see Homebrew/MacPorts command-line tools."""
    current_paths = os.environ.get("PATH", "").split(os.pathsep)
    user_tool_dir = str(get_user_tool_dir())
    merged = [user_tool_dir] + current_paths[:]
    for tool_dir in EXTRA_TOOL_DIRS:
        if tool_dir not in merged:
            merged.append(tool_dir)
    os.environ["PATH"] = os.pathsep.join(path for path in merged if path)


def find_executable(name: str) -> str | None:
    ensure_tool_path()
    user_tool = get_user_tool_path(name)
    if user_tool.exists() and os.access(user_tool, os.X_OK):
        return str(user_tool)

    bundled = _find_bundled_executable(name)
    if bundled:
        return bundled

    found = shutil.which(name)
    if found:
        return found

    extensions = [""]
    if platform.system() == "Windows":
        extensions = [".exe", ".cmd", ".bat", ""]

    for directory in EXTRA_TOOL_DIRS:
        for extension in extensions:
            candidate = Path(directory) / f"{name}{extension}"
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def get_user_tool_dir() -> Path:
    return get_config_dir() / "tools"


def get_user_tool_path(name: str) -> Path:
    extension = ".exe" if platform.system() == "Windows" else ""
    return get_user_tool_dir() / f"{name}{extension}"


def _find_bundled_executable(name: str) -> str | None:
    """Find binaries bundled by PyInstaller, especially in Windows one-file builds."""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    extensions = [""]
    if platform.system() == "Windows":
        extensions = [".exe", ".cmd", ".bat", ""]

    for extension in extensions:
        candidate = base_dir / f"{name}{extension}"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def check_dependencies() -> tuple[bool, list[str]]:
    missing: list[str] = []
    if not find_executable("yt-dlp"):
        missing.append("yt-dlp")
    if not find_executable("ffmpeg"):
        missing.append("ffmpeg")
    return not missing, missing


SUPPORTED_PLATFORM_HOSTS = {
    "YouTube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "TikTok": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com"),
    "Instagram": ("instagram.com",),
    "Twitch": ("twitch.tv",),
    "Vimeo": ("vimeo.com",),
    "Facebook": ("facebook.com", "fb.watch"),
    "X / Twitter": ("x.com", "twitter.com"),
    "Reddit": ("reddit.com", "redd.it"),
    "VK": ("vk.com", "vkvideo.ru"),
    "OK": ("ok.ru",),
}


def detect_platform(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.lower()
    for platform_name, hosts in SUPPORTED_PLATFORM_HOSTS.items():
        if any(host == item or host.endswith("." + item) for item in hosts):
            if platform_name == "YouTube" and "/shorts/" in path:
                return "YouTube Shorts"
            if platform_name == "Instagram":
                if "/reel/" in path or "/reels/" in path:
                    return "Instagram Reels"
                if "/p/" in path:
                    return "Instagram Post"
            if platform_name == "Twitch":
                if "/videos/" in path:
                    return "Twitch VOD"
                if "/clip/" in path or "clips.twitch.tv" in host:
                    return "Twitch Clip"
            return platform_name
    return "Unknown"


def is_supported_media_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    return detect_platform(url) != "Unknown"


def is_supported_youtube_url(url: str) -> bool:
    return is_supported_media_url(url)


def dependency_instructions(missing: list[str]) -> str:
    missing_text = ", ".join(missing)
    system = platform.system()

    if system == "Darwin":
        return (
            f"Missing required tools: {missing_text}\n\n"
            "Install them with Homebrew:\n"
            "  brew install yt-dlp ffmpeg"
        )

    if system == "Windows":
        return (
            f"Missing required tools: {missing_text}\n\n"
            "Install them with winget:\n"
            "  winget install yt-dlp.yt-dlp\n"
            "  winget install Gyan.FFmpeg\n\n"
            "After installing, restart this app so PATH is refreshed."
        )

    return (
        f"Missing required tools: {missing_text}\n\n"
        "Install yt-dlp and ffmpeg with your system package manager."
    )


def is_probably_external_drive(path: Path) -> bool:
    """Best-effort external-drive detection without platform-specific dependencies."""
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()

    if platform.system() == "Darwin":
        return str(resolved).startswith("/Volumes/")

    if platform.system() == "Windows":
        drive = resolved.drive.upper()
        system_drive = os.environ.get("SystemDrive", "C:").upper()
        return bool(drive and drive != system_drive)

    return False


def open_folder(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif system == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def human_error_message(raw_output: str, save_directory: Path) -> str:
    text = raw_output.lower()

    if "file too large" in text or "errno 27" in text:
        return (
            "Your drive is probably FAT32. Reformat it to exFAT to store files "
            "larger than 4 GB."
        )

    if "no space left on device" in text or "errno 28" in text:
        return "There is not enough free space on the selected drive or local disk."

    if "requested format is not available" in text or "no video formats found" in text:
        return "yt-dlp could not find the selected format. Try Quality: Best available."

    if "no such file or directory" in text or "cannot find the path" in text:
        return f"Path error. Please check the selected folder:\n{save_directory}"

    if "permission denied" in text or "access is denied" in text:
        return f"Permission error. The app cannot write to:\n{save_directory}"

    return "Download failed. Check the log output for details."
