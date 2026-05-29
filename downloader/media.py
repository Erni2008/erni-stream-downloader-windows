from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .utils import find_executable


@dataclass
class MediaReport:
    path: Path
    has_video: bool
    has_audio: bool
    video_codec: str | None = None
    audio_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    compatible: bool = False
    message: str = ""


def probe_media(path: Path) -> MediaReport:
    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        return MediaReport(path=path, has_video=False, has_audio=False, message="ffprobe не найден. Установи ffmpeg или пересобери приложение с ffmpeg.")

    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return MediaReport(path=path, has_video=False, has_audio=False, message=f"Не удалось проверить файл:\n{completed.stderr.strip()}")

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return MediaReport(path=path, has_video=False, has_audio=False, message="ffprobe вернул нечитаемый ответ.")

    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    report = MediaReport(
        path=path,
        has_video=video_stream is not None,
        has_audio=audio_stream is not None,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        width=video_stream.get("width") if video_stream else None,
        height=video_stream.get("height") if video_stream else None,
        duration=_safe_float(data.get("format", {}).get("duration")),
    )
    if video_stream:
        report.fps = _parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))

    issues: list[str] = []
    if not report.has_video:
        issues.append("файл без картинки")
    if not report.has_audio:
        issues.append("файл без звука")
    if report.video_codec not in {None, "h264"}:
        issues.append(f"video codec {report.video_codec}, лучше H.264")
    if report.audio_codec not in {None, "aac"}:
        issues.append(f"audio codec {report.audio_codec}, лучше AAC")

    report.compatible = not issues and report.has_video and report.has_audio
    if report.compatible:
        report.message = "Файл выглядит совместимым: есть видео и звук, H.264 + AAC."
    elif issues:
        report.message = "Найдены проблемы: " + "; ".join(issues) + "."
    else:
        report.message = "Файл проверен, но совместимость определить не удалось."
    return report


def repair_to_universal_mp4(source: Path, on_log=None) -> Path:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg не найден. Невозможно починить видео.")

    target = _unique_destination(source.with_name(f"{source.stem}.universal.mp4"))
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
        str(target),
    ]
    if on_log:
        on_log("Команда ремонта:\n" + " ".join(command) + "\n\n")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        if on_log:
            on_log(line)
    return_code = process.wait()
    if return_code != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg не смог создать universal MP4. Посмотри лог.")
    return target


def report_to_text(report: MediaReport) -> str:
    resolution = f"{report.width}x{report.height}" if report.width and report.height else "unknown"
    fps = f"{report.fps:g}" if report.fps else "unknown"
    duration = _format_duration(report.duration)
    return (
        f"Файл: {report.path}\n"
        f"Видео: {'есть' if report.has_video else 'нет'} ({report.video_codec or 'unknown'})\n"
        f"Звук: {'есть' if report.has_audio else 'нет'} ({report.audio_codec or 'unknown'})\n"
        f"Размер кадра: {resolution}\n"
        f"FPS: {fps}\n"
        f"Длительность: {duration}\n"
        f"Итог: {report.message}"
    )


def _parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return round(float(left) / denominator, 3)
        except ValueError:
            return None
    return _safe_float(value)


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _format_duration(value: float | None) -> str:
    if not value:
        return "unknown"
    seconds = int(value)
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique output file for {path}")
