from __future__ import annotations

import os
import concurrent.futures
import contextlib
import hashlib
import json
import queue
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .utils import human_error_message
from .utils import find_executable

try:
    import socks  # type: ignore[import-not-found]
except Exception:  # SOCKS proxy support is optional at runtime.
    socks = None


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]
FinishCallback = Callable[["DownloadResult"], None]


NETWORK_RETRY_ATTEMPTS = 60
AUTO_SOCKS_PROXY_PORTS = (1080, 10808, 2080, 2081, 7891, 9090)
AUTO_HTTP_PROXY_PORTS = (7890, 8080, 8888, 3128)

QUALITY_FORMATS = {
    "Best available": "bv*+ba/b",
    "2160p / 4K": "bestvideo[height=2160]+bestaudio/best[height=2160]/bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "1440p / 2K": "bestvideo[height=1440]+bestaudio/best[height=1440]/bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "1080p": "bestvideo[height=1080]+bestaudio/best[height=1080]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height=720]+bestaudio/best[height=720]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height=480]+bestaudio/best[height=480]/bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "360p": "bestvideo[height=360]+bestaudio/best[height=360]/bestvideo[height<=360]+bestaudio/best[height<=360]/best",
}

QUALITY_HEIGHT_LIMITS = {
    "2160p / 4K": 2160,
    "1440p / 2K": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

DOWNLOAD_MODES = [
    "Original quality",
    "Best quality MP4",
    "For editing: universal",
    "For editing: VEGAS Pro",
    "For editing: Premiere / DaVinci / CapCut",
    "For editing: Final Cut / macOS",
    "For TikTok / Reels / Shorts",
    "For archive",
    "Audio only",
    "Thumbnail only",
]

DOWNLOAD_MODE_DESCRIPTIONS = {
    "Original quality": (
        "Скачивает лучший доступный поток без перекодирования. Лучше всего для TikTok, Instagram, архива и случаев, где важно сохранить исходный FPS/resolution/codec."
    ),
    "Best quality MP4": (
        "Скачивает лучшее качество и делает один совместимый MP4 с H.264 + AAC. Хороший режим по умолчанию для просмотра и отправки."
    ),
    "For editing: universal": (
        "Максимально совместимый MP4: H.264 + AAC + constant FPS + yuv420p. Подходит почти для всего: Premiere, DaVinci, CapCut, VEGAS, Final Cut и обычные плееры."
    ),
    "For editing: VEGAS Pro": (
        "Самый совместимый вариант для VEGAS: H.264 + AAC + constant FPS + yuv420p."
    ),
    "For editing: Premiere / DaVinci / CapCut": (
        "Универсальный монтажный MP4: H.264 + AAC + constant FPS для Adobe Premiere, DaVinci Resolve и CapCut."
    ),
    "For editing: Final Cut / macOS": (
        "MP4, который легче открывается на macOS и в Final Cut: H.264 + AAC + faststart + constant FPS."
    ),
    "For TikTok / Reels / Shorts": (
        "Скачивает вертикальные ролики в лучшем доступном качестве и сохраняет как совместимый MP4 без лишних настроек."
    ),
    "For archive": (
        "Сохраняет максимально близко к оригиналу платформы без перекодирования. Файл может быть неидеален для монтажных программ."
    ),
    "Audio only": (
        "Скачивает только звук и сохраняет MP3. Полезно для подкастов, лекций, музыки и интервью."
    ),
    "Thumbnail only": (
        "Скачивает только обложку/thumbnail, если платформа отдаёт превью."
    ),
}


@dataclass
class DownloadRequest:
    url: str
    save_directory: Path
    quality: str
    output_format: str
    download_mode: str
    use_temp_first: bool
    clip_start: str = ""
    clip_end: str = ""
    estimated_size: int | None = None
    allow_playlist: bool = False
    playlist_limit: int = 10
    rf_network_profile: bool = True
    stable_network_mode: bool = True
    proxy_url: str = ""
    cookies_browser: str = "Off"


@dataclass
class DownloadResult:
    success: bool
    message: str
    output_file: Path | None = None
    output_files: list[Path] | None = None
    temp_directory: Path | None = None
    raw_output: str = ""
    log_file: Path | None = None


class DownloadWorker:
    def __init__(
        self,
        request: DownloadRequest,
        on_log: LogCallback,
        on_progress: ProgressCallback,
        on_status: StatusCallback,
        on_finish: FinishCallback,
    ) -> None:
        self.request = request
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_status = on_status
        self.on_finish = on_finish
        self._process: subprocess.Popen[str] | None = None
        self._cancel_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_lines: list[str] = []
        self._auto_proxy_url: str | None = None
        self._auto_proxy_checked = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="download-worker", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_requested.set()
        process = self._process
        if not process or process.poll() is not None:
            return

        self.on_status("Cancelling")
        self.on_log("Cancelling download...\n")

        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.on_log("Process did not stop in time. Killing it...\n")
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.kill()

    def _run(self) -> None:
        temp_dir: Path | None = None
        actual_download_dir = self.request.save_directory

        try:
            self.request.save_directory.mkdir(parents=True, exist_ok=True)
            self._ensure_preflight_space(self.request.save_directory)

            if self.request.use_temp_first:
                temp_dir = self._temporary_download_dir()
                actual_download_dir = temp_dir
                self._ensure_preflight_space(actual_download_dir)
                if any(temp_dir.iterdir()):
                    self.on_log(f"Resume download folder: {temp_dir}\n")
                else:
                    self.on_log(f"Temporary download folder: {temp_dir}\n")

            before_files = self._snapshot_files(actual_download_dir)
            downloaded_files = self._try_download_youtube_prefix_clip(actual_download_dir)
            if downloaded_files is None:
                downloaded_files = self._try_download_youtube_indexed_full(actual_download_dir)
            if downloaded_files is None:
                command = self._build_command(actual_download_dir)
                self.on_status("Downloading")
                self.on_progress(0)
                self.on_log("Running command:\n")
                self.on_log(self._display_command(command) + "\n\n")

                return_code = self._run_process(command, monitor_dir=actual_download_dir)
                raw_output = "".join(self._output_lines)

                if self._cancel_requested.is_set():
                    self.on_status("Idle")
                    self.on_finish(
                        DownloadResult(
                            success=False,
                            message="Download cancelled.",
                            temp_directory=temp_dir,
                            raw_output=raw_output,
                        )
                    )
                    return

                if return_code != 0:
                    self.on_status("Error")
                    self.on_finish(
                        DownloadResult(
                            success=False,
                            message=human_error_message(raw_output, self.request.save_directory),
                            temp_directory=temp_dir,
                            raw_output=raw_output,
                        )
                    )
                    return

                downloaded_files = self._find_new_media_files(actual_download_dir, before_files)
            raw_output = "".join(self._output_lines)
            if not downloaded_files:
                self.on_status("Error")
                self.on_finish(
                    DownloadResult(
                        success=False,
                        message="Download finished, but the output file could not be found.",
                        temp_directory=temp_dir,
                        raw_output=raw_output,
                    )
                )
                return

            final_files = [self._ensure_player_compatible_file(path) for path in downloaded_files]
            if self.request.use_temp_first:
                self.on_status("Copying")
                copied_files: list[Path] = []
                for downloaded_file in final_files:
                    copied_files.append(self._copy_to_destination(downloaded_file, self.request.save_directory))
                    downloaded_file.unlink(missing_ok=True)
                final_files = copied_files
                self._try_remove_empty_temp_dir(temp_dir)

            final_file = final_files[0]
            self.on_progress(100)
            self.on_status("Finished")
            self.on_finish(
                DownloadResult(
                    success=True,
                    message="Download finished successfully.",
                    output_file=final_file,
                    output_files=final_files,
                    temp_directory=temp_dir,
                    raw_output=raw_output,
                )
            )

        except Exception as exc:  # Keep GUI alive and show a useful error.
            self.on_status("Error")
            message = str(exc)
            if temp_dir and temp_dir.exists():
                message += f"\nTemporary files were left here:\n{temp_dir}"
            self.on_finish(DownloadResult(success=False, message=message, temp_directory=temp_dir))

    def _build_command(self, output_dir: Path) -> list[str]:
        quality_selector = self._format_selector()
        output_format = self._requested_container()
        output_template = str(output_dir / "%(title).200B.%(ext)s")

        yt_dlp = find_executable("yt-dlp") or "yt-dlp"
        ffmpeg = find_executable("ffmpeg")
        command = [
            yt_dlp,
            "--newline",
            "--no-color",
            "--windows-filenames",
            "--retries",
            "30",
            "--fragment-retries",
            "60" if self.request.stable_network_mode else "30",
            "--concurrent-fragments",
            "2" if self.request.stable_network_mode else "8",
            "--extractor-retries",
            "30" if self.request.stable_network_mode else "15",
            "--file-access-retries",
            "30" if self.request.stable_network_mode else "15",
            "--continue",
            "--no-mtime",
        ]
        self._add_network_options(command)

        if self.request.allow_playlist:
            limit = max(1, min(int(self.request.playlist_limit or 1), 200))
            command.extend(["--yes-playlist", "--playlist-end", str(limit)])
        else:
            command.append("--no-playlist")

        if self._is_thumbnail_mode():
            command.extend(["--skip-download", "--write-thumbnail", "--convert-thumbnails", "jpg"])
        elif self._is_audio_mode():
            command.extend(["-f", "ba/bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0"])
        else:
            command.extend(["-f", quality_selector, "--merge-output-format", output_format])

        section = self._download_section()
        if section:
            command.extend(["--download-sections", section])
            command.extend(["--downloader-args", "ffmpeg:-nostdin -stats_period 1 -loglevel info -rw_timeout 45000000"])
            command.extend(["--socket-timeout", "60" if self.request.stable_network_mode else "30"])
            if self._is_editing_mode():
                command.append("--force-keyframes-at-cuts")
            self.on_log(f"Clip mode enabled: {section}\n")

        if ffmpeg:
            command.extend(["--ffmpeg-location", ffmpeg])
        node = find_executable("node")
        if node:
            command.extend(["--js-runtimes", f"node:{node}"])
        command.extend(["-o", output_template, self.request.url])
        return command

    def _temporary_download_dir(self) -> Path:
        if self.request.rf_network_profile or self.request.stable_network_mode:
            key = "|".join(
                [
                    self.request.url,
                    self.request.clip_start.strip(),
                    self.request.clip_end.strip(),
                    self.request.output_format,
                    self.request.download_mode,
                ]
            )
            digest = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()[:16]
            path = Path(tempfile.gettempdir()) / f"erni-stream-resume-{digest}"
            path.mkdir(parents=True, exist_ok=True)
            return path
        return Path(tempfile.mkdtemp(prefix="erni-stream-download-"))

    def _format_selector(self) -> str:
        fallback = QUALITY_FORMATS.get(self.request.quality, QUALITY_FORMATS["Best available"])
        if self.request.quality == "Best available":
            if self._download_section() and self._requested_container().upper() == "MP4":
                return (
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo+bestaudio/"
                    "best[ext=mp4]/"
                    "bv*+ba/b"
                )
            return fallback
        if self._is_no_transcode_mode() or self._requested_container().upper() != "MP4":
            return fallback

        height = QUALITY_HEIGHT_LIMITS.get(self.request.quality)
        height_filter = f"[height<={height}]" if height else ""
        exact_height_filter = f"[height={height}]" if height else ""
        return (
            f"bestvideo{exact_height_filter}[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo{height_filter}[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"best{height_filter}[ext=mp4][vcodec^=avc1]/"
            f"{fallback}"
        )

    def _download_section(self) -> str | None:
        start = self.request.clip_start.strip()
        end = self.request.clip_end.strip()
        if not start and not end:
            return None
        return f"*{start}-{end}"

    def _try_download_youtube_prefix_clip(self, output_dir: Path) -> list[Path] | None:
        if not self._download_section() or self._is_audio_mode() or self._is_thumbnail_mode():
            return None
        if "youtube.com/" not in self.request.url and "youtu.be/" not in self.request.url:
            return None

        duration = self._requested_section_duration()
        if not duration:
            return None

        try:
            start_seconds = self._time_to_seconds(self.request.clip_start.strip())
            end_seconds = self._time_to_seconds(self.request.clip_end.strip())
        except ValueError:
            return None

        yt_dlp = find_executable("yt-dlp")
        ffmpeg = find_executable("ffmpeg")
        if not yt_dlp or not ffmpeg:
            return None

        self.on_status("Checking")
        self.on_progress(0)
        self.on_log(
            "High-quality fragment mode: downloading only the indexed segments for the selected time range, "
            "then cutting locally.\n"
        )

        info_command = [yt_dlp, "-j", "--no-playlist"]
        self._add_network_options(info_command)
        node = find_executable("node")
        if node:
            info_command.extend(["--js-runtimes", f"node:{node}"])
        info_command.append(self.request.url)
        completed = subprocess.run(
            info_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        self._output_lines.append(completed.stdout)
        if completed.stderr:
            self._output_lines.append(completed.stderr)
            self.on_log(completed.stderr)
        if completed.returncode != 0:
            self.on_log("Could not read YouTube formats.\n")
            self.on_log(completed.stdout + completed.stderr)
            raise RuntimeError("Could not read YouTube formats for high-quality local clipping.")

        try:
            info = self._parse_youtube_info_json(completed.stdout)
        except json.JSONDecodeError:
            self.on_log("Could not parse YouTube formats.\n")
            self.on_log((completed.stdout + completed.stderr)[-4000:])
            raise RuntimeError("Could not parse YouTube formats for high-quality local clipping.")

        video_candidates = self._select_prefix_clip_video_formats(info)
        audio_format = self._select_prefix_clip_audio_format(info)
        if not video_candidates:
            self.on_log("No high-quality downloadable video stream found.\n")
            raise RuntimeError("No high-quality downloadable video stream found.")

        title = self._safe_filename(str(info.get("title") or "youtube-fragment"))
        target = self._unique_destination(output_dir / f"{title}.source.{self._requested_container().lower()}")
        last_fast_error: Exception | None = None
        for attempt, video_format in enumerate(video_candidates[:6], start=1):
            work_dir = output_dir / f"{target.stem}.parts"
            shutil.rmtree(work_dir, ignore_errors=True)
            work_dir.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            embedded_audio = video_format.get("acodec") not in {None, "none"}
            video_part = work_dir / f"video.{video_format.get('ext') or 'mp4'}"
            audio_part: Path | None = None

            self.on_log(
                "Selected video: "
                f"{video_format.get('format_id')} {video_format.get('width')}x{video_format.get('height')} "
                f"{video_format.get('fps') or ''}fps {video_format.get('vcodec')} "
                f"(try {attempt}/{min(6, len(video_candidates))})\n"
            )
            try:
                video_segment_start = self._download_segment_range(
                    video_format,
                    start_seconds,
                    end_seconds,
                    video_part,
                    progress_base=0,
                    progress_span=75,
                )

                if audio_format and not embedded_audio:
                    audio_part = work_dir / f"audio.{audio_format.get('ext') or 'm4a'}"
                    self.on_log(
                        f"Selected audio: {audio_format.get('format_id')} {audio_format.get('acodec')} "
                        f"{audio_format.get('abr') or ''}k\n"
                    )
                    audio_segment_start = self._download_segment_range(
                        audio_format,
                        start_seconds,
                        end_seconds,
                        audio_part,
                        progress_base=75,
                        progress_span=15,
                    )
                else:
                    audio_segment_start = start_seconds
            except Exception as exc:
                last_fast_error = exc
                self.on_log(
                    f"Fast indexed clipping failed for format {video_format.get('format_id')}: {exc}\n"
                )
                if self._is_long_network_failure(exc):
                    self.on_log("Keeping cached segment files so the download can be retried without losing progress.\n")
                    raise
                shutil.rmtree(work_dir, ignore_errors=True)
                continue

            self.on_status("Cutting")
            self.on_log("Cutting the local high-quality fragment...\n")
            cut_command = [
                ffmpeg,
                "-y",
                "-nostdin",
                "-ss",
                f"{max(0.0, start_seconds - video_segment_start):.6f}",
                "-i",
                str(video_part),
            ]
            if audio_part:
                cut_command.extend(["-ss", f"{max(0.0, start_seconds - audio_segment_start):.6f}", "-i", str(audio_part)])
            cut_command.extend(["-t", f"{duration:.3f}", "-map", "0:v:0"])
            if audio_part:
                cut_command.extend(["-map", "1:a:0"])
            elif embedded_audio:
                cut_command.extend(["-map", "0:a:0?"])
            if self._requested_container().upper() == "MP4" or self._is_editing_mode() or duration > 15:
                cut_command.extend([
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-fps_mode",
                    "cfr",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                ])
            else:
                cut_command.extend(["-c:v", "copy", "-c:a", "copy"])
            cut_command.extend(["-movflags", "+faststart", str(target)])
            return_code = self._run_process(cut_command, monitor_dir=output_dir)
            if return_code != 0 or not target.exists() or target.stat().st_size == 0:
                last_fast_error = RuntimeError("ffmpeg could not cut the indexed fragment")
                self.on_log(f"Fast indexed cutting failed for format {video_format.get('format_id')}.\n")
                shutil.rmtree(work_dir, ignore_errors=True)
                target.unlink(missing_ok=True)
                continue

            shutil.rmtree(work_dir, ignore_errors=True)
            self.on_progress(95)
            return [target]

        self.on_log(
            f"Fast indexed clipping is not available for this video: {last_fast_error}\n"
            "Stopped instead of falling back to 360p/network ffmpeg.\n"
        )
        raise RuntimeError(
            "Could not download this clip in high quality. The app did not fall back to 360p."
        )

    def _try_download_youtube_indexed_full(self, output_dir: Path) -> list[Path] | None:
        if self._download_section() or self._is_audio_mode() or self._is_thumbnail_mode():
            return None
        if "youtube.com/" not in self.request.url and "youtu.be/" not in self.request.url:
            return None

        yt_dlp = find_executable("yt-dlp")
        ffmpeg = find_executable("ffmpeg")
        if not yt_dlp or not ffmpeg:
            return None

        self.on_status("Checking")
        self.on_progress(0)
        self.on_log(
            "Fast full-video mode: downloading indexed YouTube streams in parallel, "
            "then merging locally.\n"
        )

        info_command = [yt_dlp, "-j", "--no-playlist"]
        self._add_network_options(info_command)
        node = find_executable("node")
        if node:
            info_command.extend(["--js-runtimes", f"node:{node}"])
        info_command.append(self.request.url)
        completed = subprocess.run(
            info_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        self._output_lines.append(completed.stdout)
        if completed.stderr:
            self._output_lines.append(completed.stderr)
            self.on_log(completed.stderr)
        if completed.returncode != 0:
            self.on_log("Could not read YouTube formats. Falling back to standard yt-dlp download.\n")
            self.on_log(completed.stdout + completed.stderr)
            return None

        try:
            info = self._parse_youtube_info_json(completed.stdout)
        except json.JSONDecodeError:
            self.on_log("Could not parse YouTube formats. Falling back to standard yt-dlp download.\n")
            self.on_log((completed.stdout + completed.stderr)[-4000:])
            return None

        video_format, audio_format = self._select_prefix_clip_formats(info)
        if not video_format:
            self.on_log("No indexed video stream found. Falling back to standard yt-dlp download.\n")
            return None

        duration = self._format_duration(video_format)
        if not duration:
            return None

        title = self._safe_filename(str(info.get("title") or "youtube-video"))
        target = self._unique_destination(output_dir / f"{title}.source.{self._requested_container().lower()}")
        work_dir = output_dir / f"{target.stem}.parts"
        work_dir.mkdir(parents=True, exist_ok=True)
        video_part = work_dir / f"video.{video_format.get('ext') or 'mp4'}"
        audio_part: Path | None = None

        self.on_log(
            "Selected video: "
            f"{video_format.get('format_id')} {video_format.get('width')}x{video_format.get('height')} "
            f"{video_format.get('fps') or ''}fps {video_format.get('vcodec')}\n"
        )
        self._download_segment_range(video_format, 0.0, duration, video_part, progress_base=0, progress_span=80)

        if audio_format:
            audio_duration = self._format_duration(audio_format) or duration
            audio_part = work_dir / f"audio.{audio_format.get('ext') or 'm4a'}"
            self.on_log(
                f"Selected audio: {audio_format.get('format_id')} {audio_format.get('acodec')} "
                f"{audio_format.get('abr') or ''}k\n"
            )
            self._download_segment_range(audio_format, 0.0, audio_duration, audio_part, progress_base=80, progress_span=10)

        self.on_status("Merging")
        self.on_log("Merging the full video locally...\n")
        merge_command = [ffmpeg, "-y", "-nostdin", "-i", str(video_part)]
        if audio_part:
            merge_command.extend(["-i", str(audio_part)])
        merge_command.extend(["-map", "0:v:0"])
        if audio_part:
            merge_command.extend(["-map", "1:a:0"])
        merge_command.extend(["-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", str(target)])
        return_code = self._run_process(merge_command, monitor_dir=output_dir)
        if return_code != 0 or not target.exists() or target.stat().st_size == 0:
            raise RuntimeError(
                "Could not merge the fast full-video download. Falling back is disabled to avoid duplicate huge downloads."
            )
        shutil.rmtree(work_dir, ignore_errors=True)
        self.on_progress(95)
        return [target]

    def _select_prefix_clip_formats(self, info: dict) -> tuple[dict | None, dict | None]:
        video_formats = self._select_prefix_clip_video_formats(info)
        audio_format = self._select_prefix_clip_audio_format(info)
        return (video_formats[0] if video_formats else None, audio_format)

    @staticmethod
    def _parse_youtube_info_json(output: str) -> dict:
        cleaned = output.lstrip("\ufeff").strip()
        if not cleaned:
            raise json.JSONDecodeError("empty yt-dlp output", output, 0)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        for line in cleaned.splitlines():
            candidate = line.lstrip("\ufeff").strip()
            if not candidate.startswith("{"):
                continue
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("formats"):
                return data

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict):
                return data
        raise json.JSONDecodeError("no yt-dlp JSON object found", output, 0)

    def _select_prefix_clip_video_formats(self, info: dict) -> list[dict]:
        formats = [item for item in info.get("formats", []) if isinstance(item, dict)]
        video_only_formats = [
            item for item in formats
            if item.get("url")
            and item.get("vcodec") not in {None, "none"}
            and item.get("acodec") in {None, "none"}
            and self._format_duration(item)
            and self._format_size(item)
        ]
        video_only_formats.sort(
            key=lambda item: (
                int(item.get("height") or 0),
                int(item.get("fps") or 0),
                float(item.get("tbr") or 0),
            ),
            reverse=True,
        )
        return video_only_formats

    def _select_prefix_clip_audio_format(self, info: dict) -> dict | None:
        formats = [item for item in info.get("formats", []) if isinstance(item, dict)]
        audio_formats = [
            item for item in formats
            if item.get("url")
            and item.get("vcodec") in {None, "none"}
            and item.get("acodec") not in {None, "none"}
            and self._format_duration(item)
            and self._format_size(item)
        ]
        m4a_audio = [item for item in audio_formats if item.get("ext") == "m4a"]
        if m4a_audio:
            audio_formats = m4a_audio
        audio_formats.sort(key=lambda item: float(item.get("abr") or item.get("tbr") or 0), reverse=True)
        return audio_formats[0] if audio_formats else None

    def _download_segment_range(
        self,
        fmt: dict,
        start_seconds: float,
        end_seconds: float,
        destination: Path,
        progress_base: float,
        progress_span: float,
    ) -> float:
        duration = self._format_duration(fmt)
        size = self._format_size(fmt)
        url = fmt.get("url")
        if not duration or not size or not url:
            raise RuntimeError("Selected stream does not expose a downloadable URL.")

        try:
            return self._download_sidx_segments(
                fmt,
                start_seconds,
                end_seconds,
                destination,
                progress_base,
                progress_span,
            )
        except Exception as exc:
            raise RuntimeError(f"segment index download failed for format {fmt.get('format_id')}: {exc}") from exc

    def _download_sidx_segments(
        self,
        fmt: dict,
        start_seconds: float,
        end_seconds: float,
        destination: Path,
        progress_base: float,
        progress_span: float,
    ) -> float:
        url = str(fmt.get("url"))
        header = self._read_http_range(url, 0, 2_000_000)
        sidx_offset, sidx_size = self._find_mp4_box(header, b"sidx")
        if sidx_offset is None or sidx_size is None:
            raise RuntimeError("sidx box was not found")

        init_data = header[:sidx_offset + sidx_size]
        first_offset, references = self._parse_sidx(header[sidx_offset:sidx_offset + sidx_size])
        media_start = sidx_offset + sidx_size + first_offset
        margin = 3.0
        selected: list[tuple[int, dict]] = [
            (index, reference)
            for index, reference in enumerate(references)
            if reference["end"] >= start_seconds - margin and reference["start"] <= end_seconds + margin
        ]
        if not selected:
            raise RuntimeError("no matching media segments were found")

        segment_offsets: list[int] = []
        cursor = media_start
        for reference in references:
            segment_offsets.append(cursor)
            cursor += int(reference["size"])

        total = sum(int(reference["size"]) for _, reference in selected)
        first_segment_start = float(selected[0][1]["start"])
        self.on_status("Downloading")
        stream_size = self._format_size(fmt) or total
        if total >= stream_size * 0.95:
            self.on_log(
                f"Downloading indexed full stream for format {fmt.get('format_id')}: "
                f"{self._format_bytes(total)}.\n"
            )
        else:
            self.on_log(
                f"Downloading indexed segments for format {fmt.get('format_id')}: "
                f"{self._format_bytes(total)} instead of the whole stream.\n"
            )

        cache_dir = destination.with_name(f"{destination.name}.segments")
        cache_dir.mkdir(parents=True, exist_ok=True)
        init_file = cache_dir / "init.bin"
        if not init_file.exists() or init_file.stat().st_size != len(init_data):
            init_file.write_bytes(init_data)

        segment_jobs: list[tuple[int, int, int, Path]] = []
        for index, reference in selected:
            input_start = segment_offsets[index]
            size = int(reference["size"])
            input_end = input_start + size - 1
            segment_file = cache_dir / f"segment-{index:06d}.bin"
            segment_jobs.append((input_start, input_end, size, segment_file))

        downloaded = sum(
            size for _, _, size, segment_file in segment_jobs
            if segment_file.exists() and segment_file.stat().st_size == size
        )
        if downloaded:
            self.on_log(
                f"Resuming cached segments for format {fmt.get('format_id')}: "
                f"{self._format_bytes(downloaded)} already downloaded.\n"
            )
            self.on_progress(progress_base + min(progress_span, downloaded / max(total, 1) * progress_span))

        last_log_at = time.monotonic()
        parallel = (
            len(selected) >= 16
            and total >= 64 * 1024 * 1024
            and not self.request.stable_network_mode
            and not self._proxy_url().lower().startswith("socks")
        )
        if parallel:
            workers = min(16, max(4, len(selected)))
            self.on_log(f"Parallel segment download enabled: {workers} connections.\n")
            missing_jobs = [
                job for job in segment_jobs
                if not job[3].exists() or job[3].stat().st_size != job[2]
            ]

            def fetch_segment(item: tuple[int, int, int, Path]) -> int:
                input_start, input_end, size, segment_file = item
                return self._download_http_range_to_file(
                    url,
                    input_start,
                    input_end,
                    segment_file,
                    expected_size=size,
                    label=f"{fmt.get('format_id')} segment {segment_file.stem}",
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(fetch_segment, item) for item in missing_jobs]
                for future in concurrent.futures.as_completed(futures):
                    if self._cancel_requested.is_set():
                        for pending in futures:
                            pending.cancel()
                        raise RuntimeError("Download cancelled.")
                    downloaded += future.result()
                    progress = progress_base + min(progress_span, downloaded / max(total, 1) * progress_span)
                    self.on_progress(progress)
                    now = time.monotonic()
                    if now - last_log_at >= 1:
                        self.on_log(
                            f"[download] {fmt.get('format_id')}: "
                            f"{self._format_bytes(downloaded)} / {self._format_bytes(total)} "
                            f"({min(100, downloaded / max(total, 1) * 100):.1f}%)\n"
                        )
                        last_log_at = now
        else:
            for start_byte, end_byte, size, segment_file in segment_jobs:
                if self._cancel_requested.is_set():
                    raise RuntimeError("Download cancelled.")
                if segment_file.exists() and segment_file.stat().st_size == size:
                    continue
                written = self._download_http_range_to_file(
                    url,
                    start_byte,
                    end_byte,
                    segment_file,
                    expected_size=size,
                    label=f"{fmt.get('format_id')} segment {segment_file.stem}",
                )
                downloaded += written
                progress = progress_base + min(progress_span, downloaded / max(total, 1) * progress_span)
                self.on_progress(progress)
                now = time.monotonic()
                if now - last_log_at >= 1:
                    self.on_log(
                        f"[download] {fmt.get('format_id')}: "
                        f"{self._format_bytes(downloaded)} / {self._format_bytes(total)} "
                        f"({min(100, downloaded / max(total, 1) * 100):.1f}%)\n"
                    )
                    last_log_at = now

        self.on_status("Assembling")
        self.on_log(f"Assembling cached segments for format {fmt.get('format_id')}...\n")
        with destination.open("wb") as output:
            output.write(init_file.read_bytes())
            for _, _, size, segment_file in segment_jobs:
                if not segment_file.exists() or segment_file.stat().st_size != size:
                    raise RuntimeError(f"cached segment is missing or incomplete: {segment_file.name}")
                with segment_file.open("rb") as segment:
                    shutil.copyfileobj(segment, output, length=1024 * 1024)

        self.on_log(
            f"[download] {fmt.get('format_id')}: "
            f"{self._format_bytes(downloaded)} / {self._format_bytes(total)} (100.0%)\n"
        )
        shutil.rmtree(cache_dir, ignore_errors=True)
        return first_segment_start

    def _read_http_range(self, url: str, start: int, end: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, NETWORK_RETRY_ATTEMPTS + 1):
            try:
                with self._urlopen(request, timeout=90) as response:
                    return response.read()
            except Exception as exc:
                last_error = exc
                if self._cancel_requested.is_set():
                    raise RuntimeError("Download cancelled.") from exc
                if attempt < NETWORK_RETRY_ATTEMPTS:
                    delay = self._network_retry_delay(attempt)
                    self.on_log(
                        f"[network] Could not read YouTube data. Waiting {delay}s for VPN/proxy "
                        f"and retrying ({attempt}/{NETWORK_RETRY_ATTEMPTS}): {exc}\n"
                    )
                    time.sleep(delay)
        raise RuntimeError(str(last_error))

    def _download_http_range_to_file(
        self,
        url: str,
        start: int,
        end: int,
        destination: Path,
        expected_size: int,
        label: str,
    ) -> int:
        if destination.exists() and destination.stat().st_size == expected_size:
            return 0

        partial = destination.with_suffix(destination.suffix + ".part")
        if destination.exists() and destination.stat().st_size != expected_size:
            destination.replace(partial)
        if partial.exists() and partial.stat().st_size > expected_size:
            partial.unlink()

        bytes_at_start = partial.stat().st_size if partial.exists() else 0
        bytes_written_this_call = 0
        last_error: Exception | None = None

        for attempt in range(1, NETWORK_RETRY_ATTEMPTS + 1):
            if self._cancel_requested.is_set():
                raise RuntimeError("Download cancelled.")

            existing = partial.stat().st_size if partial.exists() else 0
            if existing == expected_size:
                partial.replace(destination)
                return expected_size
            if existing > expected_size:
                partial.unlink()
                existing = 0

            request_start = start + existing
            request = urllib.request.Request(
                url,
                headers={
                    "Range": f"bytes={request_start}-{end}",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            try:
                with self._urlopen(request, timeout=90) as response:
                    with partial.open("ab") as output:
                        while True:
                            if self._cancel_requested.is_set():
                                raise RuntimeError("Download cancelled.")
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                            bytes_written_this_call += len(chunk)

                if partial.stat().st_size == expected_size:
                    partial.replace(destination)
                    return expected_size
                last_error = RuntimeError(
                    f"incomplete segment {partial.stat().st_size} / {expected_size} bytes"
                )
            except Exception as exc:
                last_error = exc

            if attempt < NETWORK_RETRY_ATTEMPTS:
                delay = self._network_retry_delay(attempt)
                saved = partial.stat().st_size if partial.exists() else 0
                self.on_log(
                    f"[network] {label}: connection lost at {self._format_bytes(saved)} / "
                    f"{self._format_bytes(expected_size)}. Waiting {delay}s for VPN/proxy "
                    f"and continuing ({attempt}/{NETWORK_RETRY_ATTEMPTS}): {last_error}\n"
                )
                time.sleep(delay)

        raise RuntimeError(f"network did not recover while downloading {label}: {last_error}")

    @staticmethod
    def _network_retry_delay(attempt: int) -> int:
        return min(45, 3 + attempt * 2)

    def _add_network_options(self, command: list[str]) -> None:
        proxy = self._proxy_url()
        if proxy:
            command.extend(["--proxy", proxy])

        if self.request.rf_network_profile:
            command.append("--force-ipv4")

        browser = self.request.cookies_browser.strip().lower()
        if browser and browser != "off":
            command.extend(["--cookies-from-browser", browser])

    def _proxy_url(self) -> str:
        manual_proxy = self._normalize_proxy_url(self.request.proxy_url.strip())
        if manual_proxy:
            return manual_proxy
        if not self.request.rf_network_profile:
            return ""
        if not self._auto_proxy_checked:
            self._auto_proxy_checked = True
            self._auto_proxy_url = self._detect_local_proxy()
            if self._auto_proxy_url:
                self.on_log(f"RF network profile: auto-detected local proxy {self._auto_proxy_url}\n")
            else:
                self.on_log("RF network profile: no local proxy detected, using system VPN/network.\n")
        return self._auto_proxy_url or ""

    @staticmethod
    def _normalize_proxy_url(proxy: str) -> str:
        if not proxy:
            return ""
        if "://" not in proxy:
            host_port = urllib.parse.urlparse(f"//{proxy}")
            if host_port.port in AUTO_HTTP_PROXY_PORTS:
                proxy = f"http://{proxy}"
            else:
                proxy = f"socks5h://{proxy}"
        parsed = urllib.parse.urlparse(proxy)
        if parsed.scheme.lower() == "socks5":
            return urllib.parse.urlunparse(parsed._replace(scheme="socks5h"))
        return proxy

    def _detect_local_proxy(self) -> str:
        for port in AUTO_SOCKS_PROXY_PORTS:
            if self._looks_like_socks5_proxy("127.0.0.1", port):
                return f"socks5h://127.0.0.1:{port}"
        for port in AUTO_HTTP_PROXY_PORTS:
            if self._looks_like_http_proxy("127.0.0.1", port):
                return f"http://127.0.0.1:{port}"
        return ""

    @staticmethod
    def _looks_like_socks5_proxy(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.35) as sock:
                sock.settimeout(0.35)
                sock.sendall(b"\x05\x01\x00")
                response = sock.recv(2)
                return len(response) == 2 and response[0] == 5
        except OSError:
            return False

    @staticmethod
    def _looks_like_http_proxy(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.35) as sock:
                sock.settimeout(0.35)
                sock.sendall(
                    b"HEAD http://example.com/ HTTP/1.1\r\n"
                    b"Host: example.com\r\n"
                    b"Connection: close\r\n\r\n"
                )
                response = sock.recv(16)
                return response.startswith(b"HTTP/")
        except OSError:
            return False

    @contextlib.contextmanager
    def _urlopen(self, request: urllib.request.Request, timeout: int):
        proxy = self._proxy_url()
        if not proxy:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                yield response
            return

        if proxy.lower().startswith(("socks4://", "socks5://", "socks5h://")):
            if socks is None:
                raise RuntimeError("SOCKS proxy requires PySocks. Rebuild the app with PySocks installed.")
            with self._socks_socket_patch(proxy):
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    yield response
            return

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        with opener.open(request, timeout=timeout) as response:
            yield response

    @contextlib.contextmanager
    def _socks_socket_patch(self, proxy: str):
        if socks is None:
            raise RuntimeError("SOCKS proxy requires PySocks.")
        parsed = urllib.parse.urlparse(proxy)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            raise RuntimeError("SOCKS proxy must look like socks5://host:port")
        proxy_type = socks.SOCKS5
        if parsed.scheme.lower().startswith("socks4"):
            proxy_type = socks.SOCKS4
        username = urllib.parse.unquote(parsed.username or "") or None
        password = urllib.parse.unquote(parsed.password or "") or None
        original_socket = socket.socket
        socks.set_default_proxy(proxy_type, host, port, username=username, password=password)
        socket.socket = socks.socksocket  # type: ignore[assignment]
        try:
            yield
        finally:
            socket.socket = original_socket  # type: ignore[assignment]
            socks.set_default_proxy()

    @staticmethod
    def _is_long_network_failure(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "network did not recover" in text
            or "download cancelled" in text
            or "connection" in text
            or "timed out" in text
            or "timeout" in text
            or "forbidden" in text
            or "http error 403" in text
        )

    @staticmethod
    def _find_mp4_box(data: bytes, box_type: bytes) -> tuple[int | None, int | None]:
        offset = 0
        while offset + 8 <= len(data):
            size = int.from_bytes(data[offset:offset + 4], "big")
            current_type = data[offset + 4:offset + 8]
            header_size = 8
            if size == 1:
                if offset + 16 > len(data):
                    return None, None
                size = int.from_bytes(data[offset + 8:offset + 16], "big")
                header_size = 16
            if size < header_size:
                return None, None
            if current_type == box_type:
                return offset, size
            offset += size
        return None, None

    @staticmethod
    def _parse_sidx(sidx: bytes) -> tuple[int, list[dict[str, float | int]]]:
        if len(sidx) < 32 or sidx[4:8] != b"sidx":
            raise RuntimeError("invalid sidx box")
        version = sidx[8]
        position = 12
        position += 4  # reference_ID
        timescale = int.from_bytes(sidx[position:position + 4], "big")
        position += 4
        if not timescale:
            raise RuntimeError("invalid sidx timescale")
        if version == 0:
            earliest = int.from_bytes(sidx[position:position + 4], "big")
            position += 4
            first_offset = int.from_bytes(sidx[position:position + 4], "big")
            position += 4
        else:
            earliest = int.from_bytes(sidx[position:position + 8], "big")
            position += 8
            first_offset = int.from_bytes(sidx[position:position + 8], "big")
            position += 8
        position += 2  # reserved
        reference_count = int.from_bytes(sidx[position:position + 2], "big")
        position += 2
        current_time = earliest / timescale
        references: list[dict[str, float | int]] = []
        for _ in range(reference_count):
            if position + 12 > len(sidx):
                break
            first_word = int.from_bytes(sidx[position:position + 4], "big")
            position += 4
            size = first_word & 0x7FFFFFFF
            duration = int.from_bytes(sidx[position:position + 4], "big") / timescale
            position += 4
            position += 4  # SAP flags
            references.append(
                {
                    "size": size,
                    "start": current_time,
                    "end": current_time + duration,
                }
            )
            current_time += duration
        return first_offset, references

    @staticmethod
    def _format_duration(fmt: dict) -> float | None:
        value = fmt.get("duration")
        if value:
            return float(value)
        url = fmt.get("url")
        if not url:
            return None
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
        values = parsed.get("dur")
        return float(values[0]) if values else None

    @staticmethod
    def _format_size(fmt: dict) -> int | None:
        value = fmt.get("filesize") or fmt.get("filesize_approx")
        if value:
            return int(value)
        url = fmt.get("url")
        if not url:
            return None
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
        values = parsed.get("clen")
        return int(values[0]) if values else None

    @staticmethod
    def _safe_filename(value: str) -> str:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
        safe = re.sub(r"\s+", " ", safe).strip(" .")
        return safe[:160] or "youtube-fragment"

    def _requested_container(self) -> str:
        if self._is_no_transcode_mode():
            return "mkv"
        if self._is_mp4_mode():
            return "mp4"
        return self.request.output_format.lower()

    def _ensure_player_compatible_file(self, source: Path) -> Path:
        if self._is_audio_mode() or self._is_thumbnail_mode():
            return source
        if self._requested_container().upper() != "MP4":
            return source
        if self._is_no_transcode_mode():
            self.on_log("\nSkipping MP4 compatibility conversion because no-transcode mode is selected.\n")
            return source

        ffmpeg = find_executable("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "ffmpeg is required to make MP4 files compatible with Windows/macOS players."
            )

        self._ensure_conversion_space(source)
        final_target = source.with_suffix(".mp4")
        if final_target != source and final_target.exists():
            final_target = self._unique_destination(final_target)
        temp_output = self._unique_destination(source.with_name(f"{source.stem}.encoding.mp4"))
        self.on_status("Converting")
        if not self._requires_full_transcode(source):
            self.on_log("\nSource already looks MP4-compatible. Remuxing without full re-encode...\n")
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temp_output),
            ]
            return_code = self._run_process(command, monitor_dir=source.parent)
            if return_code == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
                source.unlink(missing_ok=True)
                if final_target == source:
                    temp_output.replace(final_target)
                    return final_target
                temp_output.rename(final_target)
                return final_target

            temp_output.unlink(missing_ok=True)
            temp_output = self._unique_destination(source.with_name(f"{source.stem}.encoding.mp4"))
            self.on_log("Fast remux failed. Falling back to full H.264/AAC conversion...\n")

        if self.request.download_mode == "For editing: VEGAS Pro":
            self.on_log(
                "\nMaking MP4 compatible with VEGAS Pro: H.264 video + AAC audio + constant frame rate...\n"
            )
        elif self._is_editing_mode():
            self.on_log(
                "\nMaking MP4 compatible with editing apps: H.264 video + AAC audio + constant frame rate...\n"
            )
        else:
            self.on_log(
                "\nMaking MP4 compatible with standard players: H.264 video + AAC audio in one file...\n"
            )

        command = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast" if self._is_short_fragment() else "veryfast",
            "-crf",
            "20",
            "-profile:v",
            "high",
            "-pix_fmt",
            "yuv420p",
        ]
        if self._is_editing_mode():
            command.extend(["-fps_mode", "cfr"])
        command.extend([
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(temp_output),
        ])

        return_code = self._run_process(command, monitor_dir=source.parent)
        if self._cancel_requested.is_set():
            temp_output.unlink(missing_ok=True)
            raise RuntimeError("Conversion cancelled.")
        if return_code != 0 or not temp_output.exists() or temp_output.stat().st_size == 0:
            temp_output.unlink(missing_ok=True)
            raise RuntimeError(
                "ffmpeg could not create a compatible MP4 file. Try MKV, or send the log for debugging."
            )

        source.unlink(missing_ok=True)
        if final_target == source:
            temp_output.replace(final_target)
            return final_target
        temp_output.rename(final_target)
        return final_target

    def _requires_full_transcode(self, source: Path) -> bool:
        ffprobe = find_executable("ffprobe")
        if not ffprobe:
            return True
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        if completed.returncode != 0:
            return True
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return True
        streams = data.get("streams") if isinstance(data, dict) else None
        if not streams:
            return True
        stream = streams[0]
        codec = stream.get("codec_name")
        pix_fmt = stream.get("pix_fmt")
        avg_fps = stream.get("avg_frame_rate")
        real_fps = stream.get("r_frame_rate")
        if codec != "h264" or pix_fmt != "yuv420p":
            return True
        if self._requires_constant_fps() and avg_fps != real_fps:
            return True
        return not self._has_aac_audio(source)

    def _requires_constant_fps(self) -> bool:
        mode = self.request.download_mode.lower()
        return (
            mode.startswith("for editing:")
            or self.request.download_mode.startswith("Монтаж:")
            or self.request.download_mode == "ВСЁ: максимально совместимый MP4"
        )

    def _is_short_fragment(self) -> bool:
        duration = self._requested_section_duration()
        return bool(duration and duration <= 10 * 60)

    @staticmethod
    def _has_aac_audio(source: Path) -> bool:
        ffprobe = find_executable("ffprobe")
        if not ffprobe:
            return False
        command = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(source),
        ]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0 and completed.stdout.strip().splitlines()[:1] == ["aac"]

    @staticmethod
    def _ensure_conversion_space(source: Path) -> None:
        usage = shutil.disk_usage(source.parent)
        required = int(source.stat().st_size * 1.35)
        if usage.free < required:
            raise RuntimeError(
                "Not enough free space to create a compatible MP4.\n"
                f"Free space: {usage.free / (1024 ** 3):.1f} GB\n"
                f"Recommended free space: {required / (1024 ** 3):.1f} GB"
            )

    def _ensure_preflight_space(self, destination: Path) -> None:
        if not self.request.estimated_size:
            return
        usage = shutil.disk_usage(destination)
        multiplier = 2.6 if (
            self._requested_container().upper() == "MP4"
            and not self._is_no_transcode_mode()
        ) else 1.4
        required = int(self.request.estimated_size * multiplier)
        if usage.free < required:
            raise RuntimeError(
                "Not enough free space before starting the download.\n"
                f"Free space: {usage.free / (1024 ** 3):.1f} GB\n"
                f"Recommended free space: {required / (1024 ** 3):.1f} GB"
            )

    def _is_no_transcode_mode(self) -> bool:
        mode = self.request.download_mode.lower()
        return (
            "original quality" in mode
            or "for archive" in mode
            or "без перекодирования" in mode
            or self.request.download_mode.startswith("Архив:")
        )

    def _is_editing_mode(self) -> bool:
        mode = self.request.download_mode.lower()
        return (
            mode.startswith("for editing:")
            or mode in {"best quality mp4", "for tiktok / reels / shorts"}
            or self.request.download_mode.startswith("Монтаж:")
            or self.request.download_mode == "ВСЁ: максимально совместимый MP4"
        )

    def _is_mp4_mode(self) -> bool:
        mode = self.request.download_mode.lower()
        return (
            "mp4" in mode
            or mode.startswith("for editing:")
            or mode == "for tiktok / reels / shorts"
            or self.request.output_format.upper() == "MP4"
        )

    def _is_audio_mode(self) -> bool:
        return self.request.download_mode == "Audio only"

    def _is_thumbnail_mode(self) -> bool:
        return self.request.download_mode == "Thumbnail only"

    def _run_process(self, command: list[str], monitor_dir: Path | None = None) -> int:
        creationflags = 0
        popen_kwargs: dict[str, object] = {}

        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            **popen_kwargs,
        )

        assert self._process.stdout is not None
        output_queue: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            try:
                while True:
                    char = self._process.stdout.read(1)  # type: ignore[union-attr]
                    if char == "":
                        break
                    output_queue.put(char)
            finally:
                output_queue.put(None)

        reader_thread = threading.Thread(target=reader, name="process-output-reader", daemon=True)
        reader_thread.start()

        buffer = ""
        process_started_at = time.monotonic()
        last_output_at = process_started_at
        last_heartbeat_at = process_started_at
        last_file_activity_at = process_started_at
        last_monitored_size = -1
        max_seen_progress = 0.0
        while True:
            try:
                char = output_queue.get(timeout=1)
            except queue.Empty:
                if self._cancel_requested.is_set():
                    self.cancel()
                    break
                if self._process.poll() is not None:
                    break
                now = time.monotonic()
                if now - last_heartbeat_at >= 5:
                    elapsed = int(now - process_started_at)
                    quiet = int(now - last_output_at)
                    monitor_text = ""
                    monitored_size = self._monitored_file_size(monitor_dir)
                    if monitored_size is not None:
                        if monitored_size != last_monitored_size:
                            last_file_activity_at = now
                            last_monitored_size = monitored_size
                        monitor_text = f", temp file {self._format_bytes(monitored_size)}"
                    self.on_log(
                        f"[working] Process PID {self._process.pid} is still running... "
                        f"elapsed {elapsed}s, no new output for {quiet}s{monitor_text}\n"
                    )
                    duration = self._requested_section_duration()
                    if duration:
                        max_seen_progress = max(max_seen_progress, min(95.0, (now - process_started_at) / max(duration * 4, 30) * 100))
                        self.on_progress(max_seen_progress)
                    no_file_activity = now - last_file_activity_at
                    stuck_before_output = quiet >= 45 and no_file_activity >= 45 and last_monitored_size <= 0
                    stuck_after_output = quiet >= 90 and no_file_activity >= 90
                    if stuck_before_output or stuck_after_output:
                        self.on_log(
                            "[stalled] No output and no file growth. Stopping the stuck process.\n"
                        )
                        self.cancel()
                        break
                    last_heartbeat_at = now
                continue
            if char is None:
                if self._process.poll() is not None:
                    break
                continue
            last_output_at = time.monotonic()
            if char in {"\n", "\r"}:
                if buffer:
                    line = buffer + "\n"
                    self._output_lines.append(line)
                    self.on_log(line)
                    self._parse_progress_line(buffer)
                    progress = self._progress_from_line(buffer)
                    if progress is not None:
                        max_seen_progress = max(max_seen_progress, progress)
                    buffer = ""
                continue
            buffer += char
            if self._cancel_requested.is_set():
                self.cancel()
                break

        if buffer:
            line = buffer + "\n"
            self._output_lines.append(line)
            self.on_log(line)
            self._parse_progress_line(buffer)

        return self._process.wait()

    @staticmethod
    def _monitored_file_size(directory: Path | None) -> int | None:
        if not directory or not directory.exists():
            return None
        try:
            files = [path for path in directory.rglob("*") if path.is_file()]
        except OSError:
            return None
        if not files:
            return 0
        newest = max(files, key=lambda path: path.stat().st_mtime)
        try:
            return newest.stat().st_size
        except OSError:
            return None

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ["B", "KiB", "MiB", "GiB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GiB"

    def _parse_progress_line(self, line: str) -> None:
        if "Making MP4 compatible" in line:
            self.on_status("Converting")
            return

        if "[Merger]" in line or "Merging formats into" in line:
            self.on_status("Merging")
            return

        download_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if download_match:
            self.on_status("Downloading")
            self.on_progress(float(download_match.group(1)))
            return

        time_match = re.search(r"\btime=(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", line)
        if time_match:
            self.on_status("Downloading" if self._download_section() else "Converting")
            duration = self._requested_section_duration()
            if duration:
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = float(time_match.group(3))
                current = hours * 3600 + minutes * 60 + seconds
                self.on_progress(min(99, max(0, current / duration * 100)))

    def _progress_from_line(self, line: str) -> float | None:
        download_match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if download_match:
            return float(download_match.group(1))
        time_match = re.search(r"\btime=(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", line)
        duration = self._requested_section_duration()
        if time_match and duration:
            hours = int(time_match.group(1))
            minutes = int(time_match.group(2))
            seconds = float(time_match.group(3))
            current = hours * 3600 + minutes * 60 + seconds
            return min(99, max(0, current / duration * 100))
        return None

    def _requested_section_duration(self) -> float | None:
        start = self.request.clip_start.strip()
        end = self.request.clip_end.strip()
        if not start or not end:
            return None
        try:
            start_seconds = self._time_to_seconds(start)
            end_seconds = self._time_to_seconds(end)
        except ValueError:
            return None
        if end_seconds <= start_seconds:
            return None
        return end_seconds - start_seconds

    @staticmethod
    def _time_to_seconds(value: str) -> float:
        if ":" not in value:
            return float(value)
        total = 0.0
        for part in value.split(":"):
            total = total * 60 + float(part)
        return total

    def _copy_to_destination(self, source: Path, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = self._unique_destination(destination_dir / source.name)

        total = source.stat().st_size
        copied = 0
        chunk_size = 8 * 1024 * 1024

        self.on_log(f"\nCopying to: {destination}\n")
        try:
            with source.open("rb") as src, destination.open("wb") as dst:
                while True:
                    if self._cancel_requested.is_set():
                        raise RuntimeError(f"Copy cancelled. Temporary file kept at:\n{source}")
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    if total:
                        self.on_progress(min(100, copied / total * 100))
            shutil.copystat(source, destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return destination

    @staticmethod
    def _snapshot_files(directory: Path) -> set[Path]:
        if not directory.exists():
            return set()
        return {path for path in directory.rglob("*") if path.is_file()}

    @staticmethod
    def _find_new_media_files(directory: Path, before_files: set[Path]) -> list[Path]:
        ignored_suffixes = {".part", ".ytdl", ".temp", ".tmp"}
        video_suffixes = {".mp4", ".mkv", ".webm", ".mov"}
        candidates = [
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path not in before_files
            and path.suffix.lower() not in ignored_suffixes
            and not path.name.endswith(".part-Frag")
            and not (path.suffix.lower() in video_suffixes and path.stat().st_size < 1024 * 1024)
        ]
        return sorted(candidates, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _unique_destination(path: Path) -> Path:
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 2
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _try_remove_empty_temp_dir(path: Path | None) -> None:
        if not path:
            return
        try:
            path.rmdir()
        except OSError:
            pass

    @staticmethod
    def _display_command(command: list[str]) -> str:
        return " ".join(f'"{part}"' if " " in part else part for part in command)
