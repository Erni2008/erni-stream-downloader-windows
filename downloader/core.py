from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .utils import human_error_message
from .utils import find_executable


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
StatusCallback = Callable[[str], None]
FinishCallback = Callable[["DownloadResult"], None]


QUALITY_FORMATS = {
    "Best available": "bv*+ba/b",
    "1440p / 2K": "bestvideo[height=1440]+bestaudio/best[height=1440]/bestvideo[height<=1440]+bestaudio/best[height<=1440]/best",
    "1080p": "bestvideo[height=1080]+bestaudio/best[height=1080]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height=720]+bestaudio/best[height=720]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
}


@dataclass
class DownloadRequest:
    url: str
    save_directory: Path
    quality: str
    output_format: str
    use_temp_first: bool


@dataclass
class DownloadResult:
    success: bool
    message: str
    output_file: Path | None = None
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

            if self.request.use_temp_first:
                temp_dir = Path(tempfile.mkdtemp(prefix="erni-stream-download-"))
                actual_download_dir = temp_dir
                self.on_log(f"Temporary download folder: {temp_dir}\n")

            before_files = self._snapshot_files(actual_download_dir)
            command = self._build_command(actual_download_dir)
            self.on_status("Downloading")
            self.on_progress(0)
            self.on_log("Running command:\n")
            self.on_log(self._display_command(command) + "\n\n")

            return_code = self._run_process(command)
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

            downloaded_file = self._find_new_media_file(actual_download_dir, before_files)
            if not downloaded_file:
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

            downloaded_file = self._ensure_player_compatible_file(downloaded_file)
            final_file = downloaded_file
            if self.request.use_temp_first:
                self.on_status("Copying")
                final_file = self._copy_to_destination(downloaded_file, self.request.save_directory)
                downloaded_file.unlink(missing_ok=True)
                self._try_remove_empty_temp_dir(temp_dir)

            self.on_progress(100)
            self.on_status("Finished")
            self.on_finish(
                DownloadResult(
                    success=True,
                    message="Download finished successfully.",
                    output_file=final_file,
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
        quality_selector = QUALITY_FORMATS[self.request.quality]
        output_format = self.request.output_format.lower()
        output_template = str(output_dir / "%(title).200B.%(ext)s")

        yt_dlp = find_executable("yt-dlp") or "yt-dlp"
        ffmpeg = find_executable("ffmpeg")
        command = [
            yt_dlp,
            "-f",
            quality_selector,
            "--merge-output-format",
            output_format,
            "--newline",
            "--no-color",
        ]
        if ffmpeg:
            command.extend(["--ffmpeg-location", str(Path(ffmpeg).parent)])
        command.extend(["-o", output_template, self.request.url])
        return command

    def _ensure_player_compatible_file(self, source: Path) -> Path:
        if self.request.output_format.upper() != "MP4":
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
        self.on_log(
            "\nMaking MP4 compatible with standard players and VEGAS Pro: H.264 video + AAC audio + constant frame rate...\n"
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
            "veryfast",
            "-crf",
            "20",
            "-profile:v",
            "high",
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
            "-movflags",
            "+faststart",
            str(temp_output),
        ]

        return_code = self._run_process(command)
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

    @staticmethod
    def _ensure_conversion_space(source: Path) -> None:
        usage = shutil.disk_usage(source.parent)
        required = int(source.stat().st_size * 1.35)
        if usage.free < required:
            raise RuntimeError(
                "Not enough free space to create a VEGAS-compatible MP4.\n"
                f"Free space: {usage.free / (1024 ** 3):.1f} GB\n"
                f"Recommended free space: {required / (1024 ** 3):.1f} GB"
            )

    def _run_process(self, command: list[str]) -> int:
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
        for line in self._process.stdout:
            self._output_lines.append(line)
            self.on_log(line)
            self._parse_progress_line(line)
            if self._cancel_requested.is_set():
                self.cancel()
                break

        return self._process.wait()

    def _parse_progress_line(self, line: str) -> None:
        if "Making MP4 compatible" in line:
            self.on_status("Converting")
            return

        if "[Merger]" in line or "Merging formats into" in line:
            self.on_status("Merging")
            return

        if "[download]" not in line:
            return

        match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if match:
            self.on_status("Downloading")
            self.on_progress(float(match.group(1)))

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
    def _find_new_media_file(directory: Path, before_files: set[Path]) -> Path | None:
        ignored_suffixes = {".part", ".ytdl", ".temp", ".tmp"}
        candidates = [
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path not in before_files
            and path.suffix.lower() not in ignored_suffixes
            and not path.name.endswith(".part-Frag")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_size)

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
