from __future__ import annotations

import queue
import json
import os
import platform
import re
import subprocess
import threading
import tkinter as tk
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_TEXT, TkinterDnD
except Exception:  # Drag-and-drop stays optional.
    DND_TEXT = None
    TkinterDnD = None

from downloader.config import AppConfig, get_config_dir, get_log_path, load_config, load_history, save_config, save_history
from downloader.core import DOWNLOAD_MODE_DESCRIPTIONS, DOWNLOAD_MODES, DownloadRequest, DownloadResult, DownloadWorker, QUALITY_FORMATS
from downloader.media import MediaReport, probe_media, repair_to_universal_mp4, report_to_text
from downloader.utils import (
    check_dependencies,
    detect_platform,
    dependency_instructions,
    ensure_tool_path,
    find_executable,
    get_user_tool_path,
    is_probably_external_drive,
    is_supported_media_url,
    open_folder,
)


APP_TITLE = "ERNI Stream Downloader"
APP_VERSION = "1.8.0"
GITHUB_RELEASES = {
    "Darwin": "https://api.github.com/repos/Erni2008/erni-stream-downloader-macos/releases/latest",
    "Windows": "https://api.github.com/repos/Erni2008/erni-stream-downloader-windows/releases/latest",
}
FORMATS = ["MP4", "MKV"]
STATUS_LABELS = {
    "Idle": "Ready",
    "Downloading": "Скачивание",
    "Merging": "Склейка видео и звука",
    "Converting": "Конвертация для MP4/VEGAS",
    "Copying": "Копирование",
    "Finished": "Готово",
    "Error": "Ошибка",
    "Cancelling": "Отмена",
    "Analyzing": "Анализ видео",
}

BaseTk = TkinterDnD.Tk if TkinterDnD else tk.Tk

I18N = {
    "RU": {
        "subtitle": "Профессиональная загрузка YouTube-видео для просмотра, монтажа и архива.",
        "setup_title": "Настройка загрузки",
        "setup_subtitle": "Вставь ссылку, выбери режим и запусти очередь. Можно перетащить ссылку прямо в окно.",
        "paste": "Вставить",
        "browse": "Выбрать",
        "analyze": "Проверить",
        "format_hint": "На выходе: один файл с видео + звуком",
        "preset_hint": "Выбери под задачу",
        "temp_first": "Сначала скачать локально, потом скопировать в выбранную папку",
        "temp_hint": "Рекомендуется для больших файлов, флешек и внешних дисков.",
        "download": "Скачать",
        "analyze_video": "Проверить видео",
        "cancel": "Отмена",
        "folder": "Папка",
        "update_ytdlp": "Обновить yt-dlp",
        "update_app": "Обновить app",
        "check_file": "Проверить файл",
        "repair_file": "Починить видео",
        "open_save": "Открыть папку",
        "clear_log": "Очистить лог",
        "copy_log": "Копировать лог",
        "copy_path": "Копировать путь",
        "open_file": "Открыть файл",
        "retry_failed": "Повторить ошибки",
        "smart_preset": "Smart preset",
        "quick_modes": "Быстрые режимы",
        "tools": "Инструменты",
        "platform_waiting": "Platform: waiting for link",
        "platform_detected": "Platform",
        "log": "Лог",
        "queue": "Очередь",
        "queue_subtitle": "Добавь несколько ссылок и скачивай их по очереди.",
        "link": "Ссылка",
        "status": "Статус",
        "quality": "Качество",
        "size": "Размер",
        "done": "Готово",
        "how": "Как работает",
        "how_text": "В высоком качестве YouTube часто отдаёт видео и звук отдельно. Приложение скачивает оба потока и собирает один финальный файл с видео + звуком.",
        "history": "История",
        "open": "Открыть",
        "repeat": "Повторить",
        "progress": "ПРОГРЕСС",
        "download_log": "Журнал загрузки",
        "language": "Язык",
        "youtube_url": "Video URL",
        "save_folder": "Папка сохранения",
        "format": "Формат",
        "preset": "Режим",
        "remove": "Удалить",
        "clear": "Очистить",
        "playlist_mode": "Скачивать плейлист / профиль",
        "playlist_hint": "Используй только для публичных видео, на которые у тебя есть право. Чтобы случайно не скачать слишком много, есть лимит.",
        "playlist_limit": "Лимит видео",
        "pause_queue": "Пауза после текущего",
        "resume_queue": "Продолжить очередь",
        "result": "Результат файла",
        "result_empty": "После загрузки здесь появится проверка: видео, звук, codec, FPS и совместимость.",
        "thumbnail": "Превью",
        "drop_ready": "Перетащи сюда YouTube-ссылку или текст",
        "drop_added": "Добавлено из drag-and-drop",
        "status_ready": "Готово",
        "status_downloading": "Скачивание",
        "status_merging": "Склейка видео и звука",
        "status_converting": "Конвертация",
        "status_copying": "Копирование",
        "status_finished": "Готово",
        "status_error": "Ошибка",
        "status_cancelling": "Отмена",
        "status_analyzing": "Анализ видео",
    },
    "EN": {
        "subtitle": "Download, inspect, and prepare YouTube videos for playback, editing, and archiving.",
        "setup_title": "Download setup",
        "setup_subtitle": "Paste a link, choose a preset, and start the queue. You can drop a link directly into the window.",
        "paste": "Paste",
        "browse": "Browse",
        "analyze": "Analyze",
        "format_hint": "Output: one file with video + audio",
        "preset_hint": "Choose by task",
        "temp_first": "Download locally first, then copy to selected folder",
        "temp_hint": "Recommended for large files, USB drives, and external disks.",
        "download": "Download",
        "analyze_video": "Analyze video",
        "cancel": "Cancel",
        "folder": "Folder",
        "update_ytdlp": "Update yt-dlp",
        "update_app": "Update app",
        "check_file": "Check file",
        "repair_file": "Repair video",
        "open_save": "Open folder",
        "clear_log": "Clear log",
        "copy_log": "Copy log",
        "copy_path": "Copy path",
        "open_file": "Open file",
        "retry_failed": "Retry failed",
        "smart_preset": "Smart preset",
        "quick_modes": "Quick modes",
        "tools": "Tools",
        "platform_waiting": "Platform: waiting for link",
        "platform_detected": "Platform",
        "log": "Log",
        "queue": "Queue",
        "queue_subtitle": "Add several links and download them one by one.",
        "link": "Link",
        "status": "Status",
        "quality": "Quality",
        "size": "Size",
        "done": "Done",
        "how": "How it works",
        "how_text": "At high quality YouTube often provides video and audio separately. The app downloads both streams and builds one final file with video + audio.",
        "history": "History",
        "open": "Open",
        "repeat": "Repeat",
        "progress": "PROGRESS",
        "download_log": "Download log",
        "language": "Language",
        "youtube_url": "Video URL",
        "save_folder": "Save folder",
        "format": "Format",
        "preset": "Mode",
        "remove": "Remove",
        "clear": "Clear",
        "playlist_mode": "Download playlist / profile",
        "playlist_hint": "Use only for public videos you own or have permission for. A limit prevents accidental bulk downloads.",
        "playlist_limit": "Video limit",
        "pause_queue": "Pause after current",
        "resume_queue": "Resume queue",
        "result": "File result",
        "result_empty": "After download, this card will show video, audio, codec, FPS, and compatibility.",
        "thumbnail": "Thumbnail",
        "drop_ready": "Drop a YouTube link or text here",
        "drop_added": "Added from drag-and-drop",
        "status_ready": "Ready",
        "status_downloading": "Downloading",
        "status_merging": "Merging video and audio",
        "status_converting": "Converting",
        "status_copying": "Copying",
        "status_finished": "Finished",
        "status_error": "Error",
        "status_cancelling": "Cancelling",
        "status_analyzing": "Analyzing video",
    },
}


class StreamDownloaderApp(BaseTk):
    def __init__(self) -> None:
        super().__init__()
        ensure_tool_path()
        self.title(APP_TITLE)
        self.geometry("1120x760")
        self.minsize(980, 680)

        self.config_data = load_config()
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: DownloadWorker | None = None
        self.last_output_file: Path | None = None
        self.log_file = get_log_path()
        self.pending_urls: list[str] = []
        self.queue_paused = False
        self.queue_urls: list[str] = []
        self.failed_urls: list[str] = []
        self.queue_row_ids: dict[str, str] = {}
        self.active_url: str | None = None
        self.last_analysis_url: str | None = None
        self.last_analysis_size: int | None = None
        self.history_items = load_history()
        self.selected_history_path: Path | None = None

        self.url_var = tk.StringVar()
        self.save_dir_var = tk.StringVar(value=self.config_data.save_directory)
        self.quality_var = tk.StringVar(value=self.config_data.quality)
        self.format_var = tk.StringVar(value=self.config_data.output_format)
        initial_mode = self.config_data.download_mode
        if initial_mode not in DOWNLOAD_MODES:
            legacy_modes = {
                "ВСЁ: максимально совместимый MP4": "For editing: universal",
                "Смотреть в плеере (MP4, видео + звук)": "Best quality MP4",
                "Монтаж: Premiere / DaVinci / CapCut": "For editing: Premiere / DaVinci / CapCut",
                "Монтаж: VEGAS Pro": "For editing: VEGAS Pro",
                "Монтаж: Final Cut / macOS": "For editing: Final Cut / macOS",
                "Архив: максимум качества без перекодирования": "For archive",
            }
            initial_mode = legacy_modes.get(initial_mode, "For editing: universal")
        self.mode_var = tk.StringVar(value=initial_mode)
        self.mode_hint_var = tk.StringVar(value=DOWNLOAD_MODE_DESCRIPTIONS.get(initial_mode, ""))
        self.language_var = tk.StringVar(value=self.config_data.language if self.config_data.language in I18N else "RU")
        self.temp_first_var = tk.BooleanVar(value=self.config_data.use_temp_first)
        self.allow_playlist_var = tk.BooleanVar(value=self.config_data.allow_playlist)
        self.playlist_limit_var = tk.IntVar(value=max(1, min(int(self.config_data.playlist_limit or 10), 200)))
        self.status_key = "Idle"
        self.status_var = tk.StringVar(value=self._status_label("Idle"))
        self.percent_var = tk.StringVar(value="0%")
        self.tools_var = tk.StringVar(value="Checking tools...")
        self.preview_var = tk.StringVar(value="Preview will appear after analysis.")
        self.result_var = tk.StringVar(value=self.t("result_empty"))
        self.platform_var = tk.StringVar(value=self.t("platform_waiting"))
        self.thumbnail_image: tk.PhotoImage | None = None
        self.url_var.trace_add("write", self._on_url_changed)

        self._configure_style()
        self._build_ui()
        self._check_dependencies_on_start()
        self.after(100, self._process_events)

    def t(self, key: str) -> str:
        return I18N.get(self.language_var.get(), I18N["RU"]).get(key, I18N["RU"].get(key, key))

    def _status_label(self, status: str) -> str:
        status_keys = {
            "Idle": "status_ready",
            "Downloading": "status_downloading",
            "Merging": "status_merging",
            "Converting": "status_converting",
            "Copying": "status_copying",
            "Finished": "status_finished",
            "Error": "status_error",
            "Cancelling": "status_cancelling",
            "Analyzing": "status_analyzing",
        }
        key = status_keys.get(status)
        return self.t(key) if key else STATUS_LABELS.get(status, status)

    def _configure_style(self) -> None:
        self.configure(bg="#eef3f8")
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.colors = {
            "bg": "#eef3f8",
            "panel": "#ffffff",
            "panel_soft": "#f8fafc",
            "ink": "#111827",
            "muted": "#64748b",
            "line": "#d7dee8",
            "accent": "#1f6feb",
            "accent_dark": "#1957ba",
            "accent_soft": "#e8f1ff",
            "danger": "#d92d20",
            "success": "#118c4f",
            "success_soft": "#e8f8ef",
            "log_bg": "#0b1220",
            "log_fg": "#d8e7ff",
        }

        self.style.configure("App.TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["panel"], relief="solid", borderwidth=1)
        self.style.configure("Header.TFrame", background="#111827")
        self.style.configure("SoftPanel.TFrame", background=self.colors["panel_soft"], relief="solid", borderwidth=1)
        self.style.configure("Header.TLabel", background="#111827", foreground="#ffffff", font=("TkDefaultFont", 24, "bold"))
        self.style.configure("SubHeader.TLabel", background="#111827", foreground="#b7c4d8", font=("TkDefaultFont", 12))
        self.style.configure("Version.TLabel", background="#1f2937", foreground="#dbeafe", font=("TkDefaultFont", 10, "bold"), padding=(10, 5))
        self.style.configure("SectionTitle.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 14, "bold"))
        self.style.configure("SectionSubTitle.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("TkDefaultFont", 10))
        self.style.configure("Hint.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("TkDefaultFont", 10))
        self.style.configure("SoftHint.TLabel", background=self.colors["panel_soft"], foreground=self.colors["muted"], font=("TkDefaultFont", 10))
        self.style.configure("Tool.TLabel", background="#e8f0ff", foreground=self.colors["accent_dark"], font=("TkDefaultFont", 10, "bold"), padding=(12, 6))
        self.style.configure("Field.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Status.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Value.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 12, "bold"))
        self.style.configure("Metric.TLabel", background=self.colors["panel_soft"], foreground=self.colors["ink"], font=("TkDefaultFont", 12, "bold"))
        self.style.configure("MetricName.TLabel", background=self.colors["panel_soft"], foreground=self.colors["muted"], font=("TkDefaultFont", 9, "bold"))
        self.style.configure("TEntry", fieldbackground="#ffffff", bordercolor=self.colors["line"], lightcolor=self.colors["line"], darkcolor=self.colors["line"], padding=8)
        self.style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=self.colors["line"], padding=8)
        self.style.configure("TButton", padding=(14, 9), font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Primary.TButton", background=self.colors["accent"], foreground="#ffffff", bordercolor=self.colors["accent"])
        self.style.map("Primary.TButton", background=[("active", self.colors["accent_dark"])], foreground=[("disabled", "#cbd5e1")])
        self.style.configure("Danger.TButton", background=self.colors["danger"], foreground="#ffffff", bordercolor=self.colors["danger"])
        self.style.configure("Secondary.TButton", background="#eef2f7", foreground=self.colors["ink"], bordercolor=self.colors["line"])
        self.style.configure("Card.TLabelframe", background=self.colors["panel"], bordercolor=self.colors["line"], relief="solid")
        self.style.configure("Card.TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Horizontal.TProgressbar", troughcolor="#e5eaf2", background=self.colors["accent"], bordercolor="#e5eaf2", lightcolor=self.colors["accent"], darkcolor=self.colors["accent"])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        bg = self.colors["bg"]
        panel = self.colors["panel"]
        soft = self.colors["panel_soft"]
        ink = self.colors["ink"]
        muted = self.colors["muted"]
        line = self.colors["line"]
        accent = self.colors["accent"]

        def make_button(parent: tk.Widget, text: str, command, variant: str = "secondary", state: str = "normal") -> tk.Button:
            styles = {
                "primary": (accent, "#ffffff", "#185abc"),
                "secondary": ("#eef3fb", ink, "#dbe4f0"),
                "danger": ("#dc2626", "#ffffff", "#b91c1c"),
                "ghost": ("#ffffff", ink, "#eef3fb"),
            }
            normal_bg, fg, active_bg = styles[variant]
            button = tk.Button(
                parent,
                text=text,
                command=command,
                state=state,
                bg=normal_bg,
                fg=fg,
                activebackground=active_bg,
                activeforeground=fg,
                disabledforeground="#9aa6b6",
                relief="flat",
                bd=0,
                padx=16,
                pady=10,
                cursor="hand2",
                font=("TkDefaultFont", 11, "bold"),
                highlightthickness=0,
            )
            return button

        def make_entry(parent: tk.Widget, variable: tk.StringVar) -> tk.Entry:
            return tk.Entry(
                parent,
                textvariable=variable,
                bg="#ffffff",
                fg=ink,
                insertbackground=ink,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#d9e2ef",
                highlightcolor=accent,
                font=("TkDefaultFont", 12),
            )

        root = tk.Frame(self, bg=bg)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        canvas = tk.Canvas(root, bg=bg, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        page_scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        page_scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=page_scrollbar.set)

        shell = tk.Frame(canvas, bg=bg)
        shell_window = canvas.create_window((0, 0), window=shell, anchor="nw")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)
        shell.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(shell_window, width=event.width))
        self._bind_mousewheel(canvas)

        header = tk.Frame(shell, bg="#0f172a", padx=26, pady=22)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text=APP_TITLE, bg="#0f172a", fg="#ffffff", font=("TkDefaultFont", 26, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=f"v{APP_VERSION}", bg="#172338", fg="#dbeafe", padx=12, pady=6, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, sticky="e")
        language_frame = tk.Frame(header, bg="#0f172a")
        language_frame.grid(row=0, column=2, sticky="e", padx=(12, 0))
        tk.Label(language_frame, text=self.t("language"), bg="#0f172a", fg="#b9c6d8", font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="e", padx=(0, 8))
        language_box = ttk.Combobox(language_frame, textvariable=self.language_var, values=["RU", "EN"], state="readonly", width=5)
        language_box.grid(row=0, column=1, sticky="e")
        language_box.bind("<<ComboboxSelected>>", self._on_language_changed)
        tk.Label(
            header,
            text=self.t("subtitle"),
            bg="#0f172a",
            fg="#b9c6d8",
            font=("TkDefaultFont", 12),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(7, 0))

        main = tk.Frame(shell, bg=bg)
        main.grid(row=1, column=0, sticky="nsew", pady=(18, 14))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)

        form = tk.Frame(main, bg=panel, padx=22, pady=20, highlightthickness=1, highlightbackground="#e1e8f2")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        form.columnconfigure(1, weight=1)

        tk.Label(form, text=self.t("setup_title"), bg=panel, fg=ink, font=("TkDefaultFont", 18, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(
            form,
            text=self.t("drop_ready"),
            bg="#e8f1ff",
            fg="#185abc",
            padx=12,
            pady=7,
            font=("TkDefaultFont", 9, "bold"),
        ).grid(row=0, column=2, sticky="e")
        tk.Label(form, text=self.t("setup_subtitle"), bg=panel, fg=muted, font=("TkDefaultFont", 10)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))

        platform_bar = tk.Frame(form, bg="#f8fbff", padx=12, pady=10, highlightthickness=1, highlightbackground="#dbeafe")
        platform_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        platform_bar.columnconfigure(1, weight=1)
        tk.Label(platform_bar, textvariable=self.platform_var, bg="#f8fbff", fg="#185abc", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        make_button(platform_bar, self.t("smart_preset"), self._apply_smart_preset, "secondary").grid(row=0, column=2, sticky="e")

        labels = [self.t("youtube_url"), self.t("save_folder"), self.t("quality"), self.t("format"), self.t("preset")]
        for index, text in enumerate(labels, start=3):
            tk.Label(form, text=text, bg=panel, fg=ink, font=("TkDefaultFont", 10, "bold")).grid(row=index, column=0, sticky="w", pady=8)

        make_entry(form, self.url_var).grid(row=3, column=1, sticky="ew", padx=12, pady=8, ipady=10)
        make_button(form, self.t("paste"), self._paste_url).grid(row=3, column=2, sticky="ew", pady=8)

        make_entry(form, self.save_dir_var).grid(row=4, column=1, sticky="ew", padx=12, pady=8, ipady=10)
        make_button(form, self.t("browse"), self._browse_directory).grid(row=4, column=2, sticky="ew", pady=8)

        quality_box = ttk.Combobox(form, textvariable=self.quality_var, values=list(QUALITY_FORMATS.keys()), state="readonly")
        quality_box.grid(row=5, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        make_button(form, self.t("analyze"), self._start_quality_check).grid(row=5, column=2, sticky="ew", pady=8)

        format_box = ttk.Combobox(form, textvariable=self.format_var, values=FORMATS, state="readonly")
        format_box.grid(row=6, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        tk.Label(form, text=self.t("format_hint"), bg=panel, fg=muted, font=("TkDefaultFont", 9)).grid(row=6, column=2, sticky="w", padx=(0, 4))

        mode_box = ttk.Combobox(form, textvariable=self.mode_var, values=DOWNLOAD_MODES, state="readonly")
        mode_box.grid(row=7, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        mode_box.bind("<<ComboboxSelected>>", self._on_mode_changed)
        tk.Label(form, text=self.t("preset_hint"), bg=panel, fg=muted, font=("TkDefaultFont", 9)).grid(row=7, column=2, sticky="w", padx=(0, 4))
        tk.Label(
            form,
            textvariable=self.mode_hint_var,
            bg=panel,
            fg=muted,
            wraplength=690,
            justify="left",
            font=("TkDefaultFont", 9),
        ).grid(row=8, column=1, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        quick_row = tk.Frame(form, bg=panel)
        quick_row.grid(row=9, column=1, columnspan=2, sticky="ew", padx=12, pady=(4, 10))
        tk.Label(quick_row, text=self.t("quick_modes"), bg=panel, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        make_button(quick_row, "Original", lambda: self._set_mode("Original quality"), "ghost").grid(row=0, column=1, padx=(0, 6))
        make_button(quick_row, "Universal", lambda: self._set_mode("For editing: universal"), "ghost").grid(row=0, column=2, padx=(0, 6))
        make_button(quick_row, "Reels", lambda: self._set_mode("For TikTok / Reels / Shorts"), "ghost").grid(row=0, column=3, padx=(0, 6))
        make_button(quick_row, "Audio", lambda: self._set_mode("Audio only"), "ghost").grid(row=0, column=4)

        option_box = tk.Frame(form, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        option_box.grid(row=10, column=1, columnspan=2, sticky="ew", padx=12, pady=(2, 4))
        option_box.columnconfigure(0, weight=1)
        tk.Checkbutton(
            option_box,
            text=self.t("temp_first"),
            variable=self.temp_first_var,
            bg=soft,
            fg=ink,
            activebackground=soft,
            selectcolor="#ffffff",
            font=("TkDefaultFont", 10, "bold"),
            relief="flat",
            bd=0,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(option_box, text=self.t("temp_hint"), bg=soft, fg=muted, font=("TkDefaultFont", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))
        tk.Checkbutton(
            option_box,
            text=self.t("playlist_mode"),
            variable=self.allow_playlist_var,
            bg=soft,
            fg=ink,
            activebackground=soft,
            selectcolor="#ffffff",
            font=("TkDefaultFont", 10, "bold"),
            relief="flat",
            bd=0,
        ).grid(row=2, column=0, sticky="w", pady=(10, 0))
        playlist_controls = tk.Frame(option_box, bg=soft)
        playlist_controls.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        tk.Label(playlist_controls, text=self.t("playlist_limit"), bg=soft, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Spinbox(
            playlist_controls,
            from_=1,
            to=200,
            textvariable=self.playlist_limit_var,
            width=6,
            bg="#ffffff",
            fg=ink,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d9e2ef",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(option_box, text=self.t("playlist_hint"), bg=soft, fg=muted, wraplength=690, justify="left", font=("TkDefaultFont", 9)).grid(row=4, column=0, sticky="w", pady=(4, 0))

        action_row = tk.Frame(form, bg=panel)
        action_row.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        for column in range(4):
            action_row.columnconfigure(column, weight=1)
        self.download_button = make_button(action_row, self.t("download"), self._start_download, "primary")
        self.download_button.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.check_quality_button = make_button(action_row, self.t("analyze_video"), self._start_quality_check)
        self.check_quality_button.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.cancel_button = make_button(action_row, self.t("cancel"), self._cancel_download, "danger", state="disabled")
        self.cancel_button.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.open_folder_button = make_button(action_row, self.t("folder"), self._open_output_folder, state="disabled")
        self.open_folder_button.grid(row=0, column=3, sticky="ew", pady=(0, 8))

        side = tk.Frame(main, bg=panel, padx=18, pady=18, highlightthickness=1, highlightbackground="#e1e8f2")
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        tk.Label(side, textvariable=self.tools_var, bg="#e8f1ff", fg="#185abc", padx=12, pady=8, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="ew")
        tk.Label(side, text=self.t("queue"), bg=panel, fg=ink, font=("TkDefaultFont", 16, "bold")).grid(row=1, column=0, sticky="w", pady=(18, 6))
        tk.Label(side, text=self.t("queue_subtitle"), bg=panel, fg=muted, wraplength=260, justify="left", font=("TkDefaultFont", 10)).grid(row=2, column=0, sticky="w")
        self.queue_table = ttk.Treeview(
            side,
            columns=("platform", "status", "quality", "size", "progress"),
            show="tree headings",
            height=7,
        )
        self.queue_table.heading("#0", text=self.t("link"))
        self.queue_table.heading("platform", text="Platform")
        self.queue_table.heading("status", text=self.t("status"))
        self.queue_table.heading("quality", text=self.t("quality"))
        self.queue_table.heading("size", text=self.t("size"))
        self.queue_table.heading("progress", text=self.t("done"))
        self.queue_table.column("#0", width=160, minwidth=120, stretch=True)
        self.queue_table.column("platform", width=92, minwidth=76, stretch=False)
        self.queue_table.column("status", width=82, minwidth=70, stretch=False)
        self.queue_table.column("quality", width=72, minwidth=66, stretch=False)
        self.queue_table.column("size", width=72, minwidth=64, stretch=False)
        self.queue_table.column("progress", width=62, minwidth=56, stretch=False)
        self.queue_table.grid(row=3, column=0, sticky="ew", pady=(12, 10))
        queue_buttons = tk.Frame(side, bg=panel)
        queue_buttons.grid(row=4, column=0, sticky="ew")
        queue_buttons.columnconfigure((0, 1, 2, 3), weight=1)
        make_button(queue_buttons, "+", self._add_url_to_queue, "secondary").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        make_button(queue_buttons, self.t("remove"), self._remove_selected_queue_item, "secondary").grid(row=0, column=1, sticky="ew", padx=(0, 6))
        make_button(queue_buttons, self.t("clear"), self._clear_queue_items, "secondary").grid(row=0, column=2, sticky="ew", padx=(0, 6))
        self.pause_queue_button = make_button(queue_buttons, self.t("pause_queue"), self._toggle_queue_pause, "secondary")
        self.pause_queue_button.grid(row=0, column=3, sticky="ew")
        self.retry_failed_button = make_button(queue_buttons, self.t("retry_failed"), self._retry_failed_urls, "ghost")
        self.retry_failed_button.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        tips = tk.Frame(side, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        tips.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        tk.Label(tips, text=self.t("how"), bg=soft, fg=ink, font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            tips,
            text=self.t("how_text"),
            bg=soft,
            fg=muted,
            wraplength=270,
            justify="left",
            font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        preview = tk.Frame(side, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        preview.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        preview.columnconfigure(0, weight=1)
        tk.Label(preview, text=self.t("thumbnail"), bg=soft, fg=ink, font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.thumbnail_label = tk.Label(
            preview,
            text="No preview",
            bg="#e5edf7",
            fg=muted,
            height=7,
            relief="flat",
            font=("TkDefaultFont", 10, "bold"),
        )
        self.thumbnail_label.grid(row=1, column=0, sticky="ew", pady=(8, 10))
        tk.Label(preview, textvariable=self.preview_var, bg=soft, fg=muted, wraplength=270, justify="left", font=("TkDefaultFont", 9)).grid(row=2, column=0, sticky="w")

        result_card = tk.Frame(side, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        result_card.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        tk.Label(result_card, text=self.t("result"), bg=soft, fg=ink, font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(result_card, textvariable=self.result_var, bg=soft, fg=muted, wraplength=270, justify="left", font=("TkDefaultFont", 9)).grid(row=1, column=0, sticky="w", pady=(6, 0))
        result_actions = tk.Frame(result_card, bg=soft)
        result_actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        result_actions.columnconfigure((0, 1), weight=1)
        self.open_file_button = make_button(result_actions, self.t("open_file"), self._open_last_file, "secondary", state="disabled")
        self.open_file_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.copy_path_button = make_button(result_actions, self.t("copy_path"), self._copy_last_file_path, "secondary", state="disabled")
        self.copy_path_button.grid(row=0, column=1, sticky="ew")

        tools = tk.Frame(side, bg=panel)
        tools.grid(row=8, column=0, sticky="ew", pady=(18, 0))
        tools.columnconfigure((0, 1), weight=1)
        tk.Label(tools, text=self.t("tools"), bg=panel, fg=ink, font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        make_button(tools, self.t("open_save"), self._open_save_folder, "secondary").grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        self.probe_file_button = make_button(tools, self.t("check_file"), self._select_and_probe_file)
        self.probe_file_button.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        self.repair_file_button = make_button(tools, self.t("repair_file"), self._select_and_repair_file)
        self.repair_file_button.grid(row=2, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        self.update_ytdlp_button = make_button(tools, self.t("update_ytdlp"), self._start_update_ytdlp)
        self.update_ytdlp_button.grid(row=2, column=1, sticky="ew", pady=(0, 6))
        self.check_update_button = make_button(tools, self.t("update_app"), self._start_app_update_check)
        self.check_update_button.grid(row=3, column=0, sticky="ew", padx=(0, 6), pady=(0, 6))
        make_button(tools, self.t("clear_log"), self._clear_log, "ghost").grid(row=3, column=1, sticky="ew", pady=(0, 6))
        self.open_log_button = make_button(tools, self.t("log"), self._open_log_folder, "ghost")
        self.open_log_button.grid(row=4, column=0, sticky="ew", padx=(0, 6))
        make_button(tools, self.t("copy_log"), self._copy_log_to_clipboard, "ghost").grid(row=4, column=1, sticky="ew")

        tk.Label(side, text=self.t("history"), bg=panel, fg=ink, font=("TkDefaultFont", 16, "bold")).grid(row=9, column=0, sticky="w", pady=(18, 6))
        self.history_listbox = tk.Listbox(
            side,
            height=5,
            bg="#f8fafc",
            fg=ink,
            selectbackground=accent,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d9e2ef",
            font=("TkDefaultFont", 10),
        )
        self.history_listbox.grid(row=10, column=0, sticky="ew", pady=(0, 10))
        self.history_listbox.bind("<<ListboxSelect>>", self._on_history_select)
        history_buttons = tk.Frame(side, bg=panel)
        history_buttons.grid(row=11, column=0, sticky="ew")
        history_buttons.columnconfigure((0, 1, 2), weight=1)
        make_button(history_buttons, self.t("open"), self._open_history_file, "secondary").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        make_button(history_buttons, self.t("folder"), self._open_history_folder, "secondary").grid(row=0, column=1, sticky="ew", padx=(0, 6))
        make_button(history_buttons, self.t("repeat"), self._repeat_history_url, "secondary").grid(row=0, column=2, sticky="ew")

        status_frame = tk.Frame(shell, bg=panel, padx=18, pady=16, highlightthickness=1, highlightbackground="#e1e8f2")
        status_frame.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)
        tk.Label(status_frame, text=self.t("status").upper(), bg=panel, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(status_frame, text=self.t("progress"), bg=panel, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(18, 0))
        tk.Label(status_frame, textvariable=self.status_var, bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        tk.Label(status_frame, textvariable=self.percent_var, bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=1, column=1, sticky="w", padx=(18, 0), pady=(4, 0))
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        log_panel = tk.Frame(shell, bg=panel, padx=16, pady=14, highlightthickness=1, highlightbackground="#e1e8f2")
        log_panel.grid(row=3, column=0, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        shell.rowconfigure(3, weight=1)
        tk.Label(log_panel, text=self.t("download_log"), bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.log_text = tk.Text(
            log_panel,
            wrap="word",
            height=13,
            state="disabled",
            bg=self.colors["log_bg"],
            fg=self.colors["log_fg"],
            insertbackground=self.colors["log_fg"],
            relief="flat",
            padx=14,
            pady=12,
            font=("Menlo", 11) if self.tk.call("tk", "windowingsystem") == "aqua" else ("Consolas", 10),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_panel, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self._refresh_history()
        self._refresh_tool_status()
        self._enable_drag_and_drop(root)

    def _check_dependencies_on_start(self) -> None:
        ok, missing = check_dependencies()
        self._refresh_tool_status()
        if ok:
            return
        messagebox.showerror("Missing dependencies", dependency_instructions(missing))
        self._append_log(dependency_instructions(missing) + "\n")

    def _bind_mousewheel(self, canvas: tk.Canvas) -> None:
        def on_mousewheel(event: tk.Event) -> None:
            if getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")
            else:
                delta = int(-1 * (event.delta / 120)) if event.delta else 0
                if delta:
                    canvas.yview_scroll(delta * 3, "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_mousewheel)
        canvas.bind_all("<Button-5>", on_mousewheel)

    def _on_language_changed(self, _event: object | None = None) -> None:
        self._save_current_config()
        self.status_var.set(self._status_label(self.status_key))
        for child in self.winfo_children():
            child.destroy()
        self._configure_style()
        self._build_ui()
        self._append_log(f"{self.t('language')}: {self.language_var.get()}\n")

    def _on_url_changed(self, *_args: object) -> None:
        url = self.url_var.get().strip()
        if not url:
            self.preview_var.set("Preview will appear after analysis.")
            self.platform_var.set(self.t("platform_waiting"))
            if hasattr(self, "thumbnail_label"):
                self.thumbnail_label.configure(image="", text="No preview")
                self.thumbnail_image = None
            return
        platform_name = detect_platform(url)
        if platform_name != "Unknown":
            self.platform_var.set(f"{self.t('platform_detected')}: {platform_name}")
            self.preview_var.set(f"Detected: {platform_name}\nClick Analyze to load title, quality, FPS, codecs and size.")
        else:
            self.platform_var.set("Platform: unsupported or unknown")

    def _set_mode(self, mode: str) -> None:
        if mode not in DOWNLOAD_MODES:
            return
        self.mode_var.set(mode)
        self._on_mode_changed()
        if mode == "Original quality":
            self.format_var.set("MKV")
        else:
            self.format_var.set("MP4")
        if mode in {"Original quality", "Best quality MP4", "For TikTok / Reels / Shorts", "For archive"}:
            self.quality_var.set("Best available")

    def _apply_smart_preset(self) -> None:
        platform_name = detect_platform(self.url_var.get().strip())
        if platform_name in {"TikTok", "Instagram Reels", "Instagram Post", "YouTube Shorts"}:
            self._set_mode("For TikTok / Reels / Shorts")
        elif platform_name in {"Twitch VOD", "Twitch Clip"}:
            self._set_mode("Best quality MP4")
        elif platform_name in {"Vimeo", "Facebook", "X / Twitter", "Reddit", "VK", "OK"}:
            self._set_mode("Original quality")
        elif platform_name.startswith("YouTube"):
            self._set_mode("For editing: universal")
        else:
            self._set_mode("Best quality MP4")
        self._append_log(f"Smart preset: {platform_name or 'Unknown'} -> {self.mode_var.get()}\n")

    def _enable_drag_and_drop(self, root: tk.Widget) -> None:
        if not DND_TEXT:
            self._append_log("Drag-and-drop недоступен: установи tkinterdnd2 из requirements.txt.\n")
            return

        def register_tree(widget: tk.Widget) -> None:
            try:
                widget.drop_target_register(DND_TEXT)  # type: ignore[attr-defined]
                widget.dnd_bind("<<Drop>>", self._handle_text_drop)  # type: ignore[attr-defined]
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                register_tree(child)

        register_tree(self)
        register_tree(root)

    def _handle_text_drop(self, event: object) -> None:
        raw_text = str(getattr(event, "data", "") or "").strip()
        urls = self._extract_youtube_urls(raw_text)
        if not urls:
            self._append_log("Drag-and-drop: YouTube-ссылка не найдена.\n")
            return

        first_url = urls[0]
        if not self.url_var.get().strip():
            self.url_var.set(first_url)

        added = 0
        for url in urls:
            if url not in self.queue_urls:
                self.queue_urls.append(url)
                self._queue_insert_or_update(url, platform=detect_platform(url), status="Ожидает", quality=self.quality_var.get(), size="—", progress="0%")
                added += 1
        self._append_log(f"{self.t('drop_added')}: {added}\n")

    @staticmethod
    def _extract_youtube_urls(text: str) -> list[str]:
        cleaned = text.replace("{", " ").replace("}", " ").replace("\n", " ")
        candidates = re.findall(r"https?://[^\s\"']+", cleaned)
        urls: list[str] = []
        for candidate in candidates:
            url = candidate.rstrip(".,);]")
            if is_supported_media_url(url) and url not in urls:
                urls.append(url)
        return urls

    def _on_mode_changed(self, _event: object | None = None) -> None:
        mode = self.mode_var.get()
        self.mode_hint_var.set(DOWNLOAD_MODE_DESCRIPTIONS.get(mode, ""))

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            messagebox.showwarning("Clipboard", "Clipboard is empty or does not contain text.")
            return

        urls = self._extract_youtube_urls(text)
        if not urls:
            self.url_var.set(text)
            return

        self.url_var.set(urls[0])
        added = 0
        for url in urls:
            if url not in self.queue_urls:
                self.queue_urls.append(url)
                self._queue_insert_or_update(url, platform=detect_platform(url), status="Ожидает", quality=self.quality_var.get(), size="—", progress="0%")
                added += 1
        if len(urls) > 1:
            self._append_log(f"Paste: добавлено ссылок в очередь: {added}\n")

    def _browse_directory(self) -> None:
        initial = self.save_dir_var.get() or str(Path.home())
        directory = filedialog.askdirectory(initialdir=initial)
        if directory:
            self.save_dir_var.set(directory)
            self._warn_if_external_drive(Path(directory))

    def _add_url_to_queue(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning(self.t("queue"), "Сначала вставь YouTube-ссылку.")
            return
        if not is_supported_media_url(url):
            messagebox.showwarning(self.t("queue"), "Эта платформа пока не поддерживается.")
            return
        if url in self.queue_urls:
            messagebox.showinfo(self.t("queue"), "Эта ссылка уже есть в очереди.")
            return
        self.queue_urls.append(url)
        self._queue_insert_or_update(url, platform=detect_platform(url), status="Ожидает", quality=self.quality_var.get(), size="—", progress="0%")
        self.url_var.set("")

    def _remove_selected_queue_item(self) -> None:
        selected = list(self.queue_table.selection())
        for row_id in selected:
            values = self.queue_table.item(row_id, "values")
            url = self._url_from_queue_row(row_id)
            self.queue_table.delete(row_id)
            if url in self.queue_urls:
                self.queue_urls.remove(url)
            self.queue_row_ids.pop(url, None)

    def _clear_queue_items(self) -> None:
        self.queue_urls.clear()
        self.queue_row_ids.clear()
        for row_id in self.queue_table.get_children():
            self.queue_table.delete(row_id)

    def _retry_failed_urls(self) -> None:
        if not self.failed_urls:
            messagebox.showinfo(self.t("queue"), "Нет ссылок с ошибкой для повтора.")
            return
        added = 0
        for url in list(self.failed_urls):
            if url not in self.queue_urls:
                self.queue_urls.append(url)
                added += 1
            self._queue_insert_or_update(url, platform=detect_platform(url), status="Ожидает повтор", quality=self.quality_var.get(), size="—", progress="0%")
        self.failed_urls.clear()
        self._append_log(f"\nДобавлено для повтора: {added}\n")

    def _queue_insert_or_update(
        self,
        url: str,
        platform: str | None = None,
        status: str | None = None,
        quality: str | None = None,
        size: str | None = None,
        progress: str | None = None,
    ) -> None:
        row_id = self.queue_row_ids.get(url)
        if not row_id:
            label = self._short_url_label(url)
            row_id = self.queue_table.insert(
                "",
                "end",
                text=label,
                values=(platform or detect_platform(url), status or "Ожидает", quality or self.quality_var.get(), size or "—", progress or "0%"),
            )
            self.queue_row_ids[url] = row_id
            return
        current = list(self.queue_table.item(row_id, "values"))
        while len(current) < 5:
            current.append("")
        if platform is not None:
            current[0] = platform
        if status is not None:
            current[1] = status
        if quality is not None:
            current[2] = quality
        if size is not None:
            current[3] = size
        if progress is not None:
            current[4] = progress
        self.queue_table.item(row_id, values=tuple(current))

    def _url_from_queue_row(self, row_id: str) -> str:
        for url, existing_id in self.queue_row_ids.items():
            if existing_id == row_id:
                return url
        return ""

    @staticmethod
    def _short_url_label(url: str) -> str:
        clean = url.replace("https://", "").replace("http://", "")
        return clean[:42] + ("..." if len(clean) > 42 else "")

    def _start_download(self) -> None:
        if self.pending_urls and self.queue_paused and not self.worker:
            self.queue_paused = False
            self._refresh_pause_button()
            self.download_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self._append_log("\nОчередь продолжена.\n")
            self._start_next_download()
            return

        urls = self._collect_download_urls()
        if not urls:
            return
        self.pending_urls = urls
        for url in urls:
            if url not in self.queue_urls:
                self.queue_urls.append(url)
            self._queue_insert_or_update(url, platform=detect_platform(url), status="Ожидает", quality=self.quality_var.get(), size="—", progress="0%")
        self._clear_log()
        self._write_log_file(
            f"\n=== {APP_TITLE} {APP_VERSION} session {datetime.now().isoformat(timespec='seconds')} ===\n"
            f"Queue size: {len(self.pending_urls)}\n"
            f"Save directory: {Path(self.save_dir_var.get().strip()).expanduser()}\n"
            f"Quality: {self.quality_var.get()}\n"
            f"Format: {self.format_var.get()}\n"
            f"Mode: {self.mode_var.get()}\n"
            f"Temp first: {self.temp_first_var.get()}\n\n"
            f"Playlist/profile mode: {self.allow_playlist_var.get()}\n"
            f"Playlist limit: {self._playlist_limit()}\n\n"
        )
        self._start_next_download()

    def _collect_download_urls(self) -> list[str] | None:
        urls = list(self.queue_urls)
        typed_url = self.url_var.get().strip()
        if typed_url and typed_url not in urls:
            urls.insert(0, typed_url)

        if not urls:
            messagebox.showwarning("Missing URL", "Paste a video URL first.")
            return None

        invalid = [url for url in urls if not is_supported_media_url(url)]
        if invalid:
            messagebox.showwarning(
                "Unsupported URL",
                "В очереди есть ссылка с неподдерживаемой платформой:\n" + invalid[0],
            )
            return None

        save_directory = Path(self.save_dir_var.get().strip()).expanduser()

        if not self.save_dir_var.get().strip():
            messagebox.showwarning("Missing folder", "Choose a save directory first.")
            return None
        if save_directory.exists() and not save_directory.is_dir():
            messagebox.showerror("Folder error", f"This path is not a folder:\n{save_directory}")
            return None

        ok, missing = check_dependencies()
        if not ok:
            messagebox.showerror("Missing dependencies", dependency_instructions(missing))
            return None

        if is_probably_external_drive(save_directory) and not self.temp_first_var.get():
            proceed = messagebox.askyesno(
                "External drive warning",
                "For large videos it is safer to download to local disk first and then copy to the drive.\n\n"
                "You selected an external drive and disabled temporary local download.\n"
                "Do you want to continue anyway?",
            )
            if not proceed:
                return None

        if self.allow_playlist_var.get():
            proceed = messagebox.askyesno(
                self.t("playlist_mode"),
                "Этот режим может скачать несколько видео из плейлиста/профиля.\n\n"
                f"Лимит: {self._playlist_limit()} видео.\n"
                "Используй только публичные видео, на которые у тебя есть право.\n\n"
                "Продолжить?",
            )
            if not proceed:
                return None

        self._save_current_config()
        return urls

    def _start_next_download(self) -> None:
        if self.queue_paused:
            self.worker = None
            self.download_button.configure(text=self.t("resume_queue"), state="normal")
            self.cancel_button.configure(state="disabled")
            self._set_status("Idle")
            self._append_log(f"\nОчередь на паузе. Осталось: {len(self.pending_urls)}\n")
            return

        if not self.pending_urls:
            self.download_button.configure(state="normal")
            self.download_button.configure(text=self.t("download"))
            self.cancel_button.configure(state="disabled")
            self._set_status("Finished")
            messagebox.showinfo("Finished", "Очередь загрузок завершена.")
            return

        url = self.pending_urls.pop(0)
        self._start_single_download(url)

    def _start_single_download(self, url: str) -> None:
        save_directory = Path(self.save_dir_var.get().strip()).expanduser()
        self.active_url = url
        self.progress["value"] = 0
        self.percent_var.set("0%")
        self.last_output_file = None
        self.open_folder_button.configure(state="disabled")
        self._set_status("Analyzing")
        self._queue_insert_or_update(url, status=self.t("analyze"), quality=self.quality_var.get(), progress="0%")
        self._append_log(f"\n--- Новая загрузка ---\nURL: {url}\n")
        self._append_log(f"Detected: {detect_platform(url)}\n")
        analysis = self._analyze_video_sync(url)
        estimated_size = None
        if analysis:
            estimated_size = analysis.get("estimated_size")
            self.last_analysis_url = url
            self.last_analysis_size = estimated_size
            self._queue_insert_or_update(
                url,
                size=self._format_bytes(estimated_size) if isinstance(estimated_size, int) else "—",
            )
            self._append_log(self._analysis_message(analysis) + "\n")
            self.preview_var.set(self._preview_message(analysis))
            self._start_thumbnail_fetch(analysis)
        else:
            self._append_log("Автоанализ не удался. Продолжаю без точной оценки размера.\n")

        request = DownloadRequest(
            url=url,
            save_directory=save_directory,
            quality=self.quality_var.get(),
            output_format=self.format_var.get(),
            download_mode=self.mode_var.get(),
            use_temp_first=self.temp_first_var.get(),
            estimated_size=estimated_size,
            allow_playlist=self.allow_playlist_var.get(),
            playlist_limit=self._playlist_limit(),
        )

        self.worker = DownloadWorker(
            request=request,
            on_log=lambda line: self.event_queue.put(("log", line)),
            on_progress=lambda value: self.event_queue.put(("progress", value)),
            on_status=lambda value: self.event_queue.put(("status", value)),
            on_finish=lambda result: self.event_queue.put(("finish", result)),
        )
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._set_status("Downloading")
        self.worker.start()

    def _toggle_queue_pause(self) -> None:
        self.queue_paused = not self.queue_paused
        self._refresh_pause_button()
        if self.queue_paused:
            self._append_log("\nПауза включена: текущая загрузка завершится, следующая не начнётся.\n")
        else:
            self._append_log("\nПауза выключена.\n")
            if self.pending_urls and not self.worker:
                self.download_button.configure(state="disabled")
                self.cancel_button.configure(state="normal")
                self._start_next_download()

    def _refresh_pause_button(self) -> None:
        if hasattr(self, "pause_queue_button"):
            self.pause_queue_button.configure(text=self.t("resume_queue") if self.queue_paused else self.t("pause_queue"))
        if hasattr(self, "download_button") and self.queue_paused and self.pending_urls and not self.worker:
            self.download_button.configure(text=self.t("resume_queue"))
        elif hasattr(self, "download_button"):
            self.download_button.configure(text=self.t("download"))

    def _playlist_limit(self) -> int:
        try:
            value = int(self.playlist_limit_var.get())
        except (tk.TclError, ValueError):
            value = 10
        return max(1, min(value, 200))

    def _start_quality_check(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a video URL first.")
            return
        if not is_supported_media_url(url):
            messagebox.showwarning("Unsupported URL", "Please paste a supported video URL.")
            return

        ok, missing = check_dependencies()
        if not ok:
            messagebox.showerror("Missing dependencies", dependency_instructions(missing))
            return

        self._clear_log()
        self.status_var.set("Проверяю качество")
        self.percent_var.set("0%")
        self.progress["value"] = 0
        self.check_quality_button.configure(state="disabled")
        self._append_log(f"Проверяю ссылку. Platform: {detect_platform(url)}...\n\n")

        thread = threading.Thread(target=self._run_quality_check, args=(url,), daemon=True)
        thread.start()

    def _run_quality_check(self, url: str) -> None:
        analysis = self._analyze_video_sync(url, emit_log=True)
        if not analysis:
            self.event_queue.put(("quality_result", (False, "Не удалось прочитать данные видео. Посмотри лог.", None, None, None)))
            return

        raw_height = analysis.get("max_height")
        max_height = raw_height if isinstance(raw_height, int) else None
        has_1440 = bool(max_height and max_height >= 1440)
        recommendation = self._recommended_quality_for_height(max_height)
        if max_height:
            if has_1440:
                if max_height > 1440:
                    message = (
                        f"Найдено максимальное качество: {max_height}p.\n\n"
                        "Настоящий 2K / 1440p доступен, но у видео есть качество выше 2K.\n"
                        f"Для самого максимального качества ставь Quality: {recommendation}.\n"
                        "Если нужен именно 2K, ставь Quality: 1440p / 2K."
                    )
                else:
                    message = (
                        f"Найдено максимальное качество: {max_height}p.\n\n"
                        "Настоящий 2K / 1440p доступен. Для максимального качества ставь Quality: 1440p / 2K."
                    )
            else:
                message = (
                    f"Найдено максимальное качество: {max_height}p.\n\n"
                    f"Настоящего 2K / 1440p нет. Лучше ставить Quality: {recommendation}."
                )
        else:
            message = (
                "Не удалось надежно определить максимальное качество по списку форматов.\n\n"
                "Попробуй Quality: Best available."
            )
        self.event_queue.put(("quality_result", (has_1440, message, max_height, recommendation, analysis)))

    def _analyze_video_sync(self, url: str, emit_log: bool = False) -> dict[str, object] | None:
        yt_dlp = find_executable("yt-dlp") or "yt-dlp"
        command = [yt_dlp, "-J", "--no-playlist", "--no-warnings", url]
        if emit_log:
            self.event_queue.put(("log", "Команда анализа:\n" + " ".join(command) + "\n\n"))
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                check=False,
            )
        except Exception as exc:
            if emit_log:
                self.event_queue.put(("log", f"Ошибка анализа: {exc}\n"))
            return None

        if completed.returncode != 0:
            if emit_log:
                self.event_queue.put(("log", completed.stderr + "\n"))
            return None

        try:
            info = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None

        formats = info.get("formats") or []
        heights: list[int] = []
        widths: list[int] = []
        fps_values: list[float] = []
        video_codecs: set[str] = set()
        audio_codecs: set[str] = set()
        has_video = False
        has_audio = False
        for item in formats:
            if not isinstance(item, dict):
                continue
            height = item.get("height")
            if isinstance(height, int) and 200 <= height <= 5000:
                heights.append(height)
            width = item.get("width")
            if isinstance(width, int) and 200 <= width <= 10000:
                widths.append(width)
            fps = item.get("fps")
            if isinstance(fps, (int, float)) and fps > 0:
                fps_values.append(float(fps))
            vcodec = str(item.get("vcodec") or "none")
            acodec = str(item.get("acodec") or "none")
            if vcodec != "none":
                has_video = True
                video_codecs.add(vcodec.split(".")[0])
            if acodec != "none":
                has_audio = True
                audio_codecs.add(acodec.split(".")[0])

        estimated_size = self._estimate_size_for_selected_quality(formats)
        return {
            "platform": detect_platform(url),
            "title": info.get("title") or "Unknown title",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "max_width": max(widths) if widths else None,
            "max_height": max(heights) if heights else None,
            "max_fps": max(fps_values) if fps_values else None,
            "has_video": has_video,
            "has_audio": has_audio,
            "video_codecs": ", ".join(sorted(video_codecs)) if video_codecs else "unknown",
            "audio_codecs": ", ".join(sorted(audio_codecs)) if audio_codecs else "unknown",
            "estimated_size": estimated_size,
            "format_count": len(formats),
        }

    def _estimate_size_for_selected_quality(self, formats: list[object]) -> int | None:
        height_limit = self._height_limit_for_quality(self.quality_var.get())
        video_sizes: list[int] = []
        audio_sizes: list[int] = []
        fallback_sizes: list[int] = []
        for item in formats:
            if not isinstance(item, dict):
                continue
            size = item.get("filesize") or item.get("filesize_approx")
            if not isinstance(size, int) or size <= 0:
                continue
            height = item.get("height")
            vcodec = str(item.get("vcodec") or "none")
            acodec = str(item.get("acodec") or "none")
            if height_limit and isinstance(height, int) and height > height_limit:
                continue
            if vcodec != "none" and acodec == "none":
                video_sizes.append(size)
            elif acodec != "none" and vcodec == "none":
                audio_sizes.append(size)
            else:
                fallback_sizes.append(size)

        if video_sizes:
            return max(video_sizes) + (max(audio_sizes) if audio_sizes else 0)
        if fallback_sizes:
            return max(fallback_sizes)
        if audio_sizes:
            return max(audio_sizes)
        return None

    @staticmethod
    def _height_limit_for_quality(quality: str) -> int | None:
        if "1440" in quality:
            return 1440
        if "1080" in quality:
            return 1080
        if "720" in quality:
            return 720
        return None

    def _analysis_message(self, analysis: dict[str, object]) -> str:
        title = analysis.get("title") or "Unknown title"
        platform_name = analysis.get("platform") or "Unknown"
        max_width = analysis.get("max_width")
        max_height = analysis.get("max_height")
        max_fps = analysis.get("max_fps")
        estimated_size = analysis.get("estimated_size")
        duration = analysis.get("duration")
        thumbnail = analysis.get("thumbnail")
        recommendation = self._recommended_quality_for_height(max_height if isinstance(max_height, int) else None)
        lines = [
            "Автоанализ видео:",
            f"Платформа: {platform_name}",
            f"Название: {title}",
            f"Resolution: {max_width}x{max_height}" if isinstance(max_width, int) and isinstance(max_height, int) else "Resolution: не удалось определить",
            f"Максимальное качество: {max_height}p" if max_height else "Максимальное качество: не удалось определить",
            f"FPS: {max_fps:g}" if isinstance(max_fps, float) else "FPS: не удалось определить",
            f"Видео codec: {analysis.get('video_codecs')}",
            f"Аудио codec: {analysis.get('audio_codecs')}",
            "Видео: есть" if analysis.get("has_video") else "Видео: не найдено",
            "Звук: есть" if analysis.get("has_audio") else "Звук: не найден",
            f"Примерный размер выбранного качества: {self._format_bytes(estimated_size)}" if isinstance(estimated_size, int) else "Примерный размер выбранного качества: не удалось определить",
            f"Длительность: {self._format_duration(duration)}" if isinstance(duration, (int, float)) else "Длительность: не удалось определить",
            f"Рекомендация: Quality = {recommendation}",
        ]
        if isinstance(thumbnail, str) and thumbnail:
            lines.append(f"Thumbnail: {thumbnail}")
        return "\n".join(lines)

    def _preview_message(self, analysis: dict[str, object]) -> str:
        max_width = analysis.get("max_width")
        max_height = analysis.get("max_height")
        size = analysis.get("estimated_size")
        parts = [
            f"Detected: {analysis.get('platform') or 'Unknown'}",
            f"Title: {analysis.get('title') or 'Unknown'}",
        ]
        if isinstance(max_width, int) and isinstance(max_height, int):
            parts.append(f"Quality: {max_width}x{max_height}")
        if isinstance(analysis.get("max_fps"), float):
            parts.append(f"FPS: {analysis['max_fps']:g}")
        parts.append(f"Video: {'yes' if analysis.get('has_video') else 'no'}")
        parts.append(f"Audio: {'yes' if analysis.get('has_audio') else 'no'}")
        parts.append(f"Codecs: {analysis.get('video_codecs')} / {analysis.get('audio_codecs')}")
        if isinstance(size, int):
            parts.append(f"Selected size: {self._format_bytes(size)}")
        return "\n".join(parts)

    @staticmethod
    def _format_bytes(value: object) -> str:
        if not isinstance(value, int) or value <= 0:
            return "unknown"
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        size = float(value)
        unit = units[0]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                break
            size /= 1024
        return f"{size:.2f} {unit}"

    @staticmethod
    def _format_duration(value: object) -> str:
        seconds = int(value) if isinstance(value, (int, float)) else 0
        hours, rem = divmod(seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_output_has_1440p(output: str) -> bool:
        max_height = StreamDownloaderApp._max_video_height_from_format_output(output)
        return bool(max_height and max_height >= 1440)

    @staticmethod
    def _max_video_height_from_format_output(output: str) -> int | None:
        heights: list[int] = []
        for line in output.splitlines():
            lowered = line.lower()
            if "audio only" in lowered:
                continue

            for width, height in re.findall(r"(?<!\d)(\d{3,5})x(\d{3,5})(?!\d)", lowered):
                w = int(width)
                h = int(height)
                if 200 <= h <= 5000 and w >= h:
                    heights.append(h)

            for height in re.findall(r"(?<!\d)([1-9]\d{2,3})p(?!\d)", lowered):
                h = int(height)
                if 200 <= h <= 5000:
                    heights.append(h)

        return max(heights) if heights else None

    @staticmethod
    def _recommended_quality_for_height(height: int | None) -> str:
        if not height:
            return "Best available"
        if height > 1440:
            return "Best available"
        if height == 1440:
            return "1440p / 2K"
        if height >= 1080:
            return "1080p"
        if height >= 720:
            return "720p"
        return "Best available"

    def _cancel_download(self) -> None:
        self.pending_urls.clear()
        self.queue_paused = False
        self._refresh_pause_button()
        if self.worker:
            self.worker.cancel()
        self.cancel_button.configure(state="disabled")

    def _start_update_ytdlp(self) -> None:
        self.update_ytdlp_button.configure(state="disabled")
        self._append_log("\nПроверяю обновление yt-dlp...\n")
        thread = threading.Thread(target=self._run_update_ytdlp, daemon=True)
        thread.start()

    def _run_update_ytdlp(self) -> None:
        system = platform.system()
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        if system != "Windows":
            url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"

        target = get_user_tool_path("yt-dlp")
        temp_target = target.with_suffix(target.suffix + ".download")
        self.event_queue.put(("log", f"Скачиваю свежий yt-dlp:\n{url}\nВ файл:\n{target}\n\n"))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, temp_target)
            if system != "Windows":
                os.chmod(temp_target, 0o755)
            temp_target.replace(target)
        except Exception as exc:
            self.event_queue.put(("update_ytdlp_result", (False, f"Не удалось обновить yt-dlp:\n{exc}")))
            return

        self.event_queue.put(("update_ytdlp_result", (True, f"yt-dlp обновлён внутри приложения:\n{target}")))

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "progress":
                    value = float(payload)
                    self.progress["value"] = value
                    self.percent_var.set(f"{value:.1f}%")
                    if self.active_url:
                        self._queue_insert_or_update(self.active_url, progress=f"{value:.1f}%")
                elif event == "status":
                    self._set_status(str(payload))
                    if self.active_url:
                        self._queue_insert_or_update(self.active_url, status=self._status_label(str(payload)))
                elif event == "finish":
                    self._handle_finish(payload)  # type: ignore[arg-type]
                elif event == "quality_result":
                    self._handle_quality_result(payload)  # type: ignore[arg-type]
                elif event == "thumbnail_result":
                    self._handle_thumbnail_result(payload)  # type: ignore[arg-type]
                elif event == "update_ytdlp_result":
                    self._handle_update_ytdlp_result(payload)  # type: ignore[arg-type]
                elif event == "probe_result":
                    self._handle_probe_result(payload)  # type: ignore[arg-type]
                elif event == "repair_result":
                    self._handle_repair_result(payload)  # type: ignore[arg-type]
                elif event == "app_update_result":
                    self._handle_app_update_result(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _handle_update_ytdlp_result(self, payload: tuple[bool, str]) -> None:
        success, message = payload
        self.update_ytdlp_button.configure(state="normal")
        self._append_log("\n" + message + "\n")
        if success:
            messagebox.showinfo("yt-dlp", message)
        else:
            messagebox.showwarning("yt-dlp", message)

    def _handle_quality_result(self, payload: tuple[bool, str, int | None, str | None, dict[str, object] | None]) -> None:
        has_1440, message, max_height, recommendation, analysis = payload
        self.check_quality_button.configure(state="normal")
        self._set_status("Idle")
        self._append_log("\nРезультат проверки качества:\n" + message + "\n")
        if analysis:
            self.last_analysis_url = self.url_var.get().strip()
            size = analysis.get("estimated_size")
            self.last_analysis_size = size if isinstance(size, int) else None
            self.preview_var.set(self._preview_message(analysis))
            self._start_thumbnail_fetch(analysis)
            self._append_log("\n" + self._analysis_message(analysis) + "\n")
        if max_height:
            self._append_log(f"Максимум найдено: {max_height}p\n")
        if recommendation:
            self._append_log(f"Рекомендация: Quality = {recommendation}\n")
        if has_1440:
            messagebox.showinfo("2K доступен", message)
        else:
            messagebox.showwarning("Рекомендация по качеству", message)

    def _start_thumbnail_fetch(self, analysis: dict[str, object]) -> None:
        thumbnail = analysis.get("thumbnail")
        if not isinstance(thumbnail, str) or not thumbnail:
            if hasattr(self, "thumbnail_label"):
                self.thumbnail_label.configure(image="", text="No preview")
                self.thumbnail_image = None
            return
        if hasattr(self, "thumbnail_label"):
            self.thumbnail_label.configure(image="", text="Loading preview...")
        thread = threading.Thread(target=self._thumbnail_worker, args=(thumbnail,), daemon=True)
        thread.start()

    def _thumbnail_worker(self, thumbnail_url: str) -> None:
        try:
            thumb_dir = get_config_dir() / "thumbnails"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            raw_path = thumb_dir / "latest-thumbnail"
            png_path = thumb_dir / "latest-thumbnail.png"
            request = urllib.request.Request(thumbnail_url, headers={"User-Agent": APP_TITLE})
            with urllib.request.urlopen(request, timeout=15) as response:
                raw_path.write_bytes(response.read())

            ffmpeg = find_executable("ffmpeg")
            if ffmpeg:
                completed = subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(raw_path),
                        "-vf",
                        "scale=320:-1",
                        "-frames:v",
                        "1",
                        str(png_path),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                )
                if completed.returncode == 0 and png_path.exists():
                    self.event_queue.put(("thumbnail_result", png_path))
                    return
            self.event_queue.put(("thumbnail_result", None))
        except Exception:
            self.event_queue.put(("thumbnail_result", None))

    def _handle_thumbnail_result(self, path: Path | None) -> None:
        if not hasattr(self, "thumbnail_label"):
            return
        if not path or not path.exists():
            self.thumbnail_label.configure(image="", text="Preview unavailable")
            self.thumbnail_image = None
            return
        try:
            image = tk.PhotoImage(file=str(path))
        except tk.TclError:
            self.thumbnail_label.configure(image="", text="Preview unavailable")
            self.thumbnail_image = None
            return
        self.thumbnail_image = image
        self.thumbnail_label.configure(image=image, text="")

    def _result_card_text(self, path: Path, report: MediaReport) -> str:
        verdict = "OK: файл совместим" if report.compatible else "Нужно починить: " + report.message
        video = "есть" if report.has_video else "нет картинки"
        audio = "есть" if report.has_audio else "нет звука"
        resolution = f"{report.width}x{report.height}" if report.width and report.height else "unknown"
        fps = f"{report.fps:g}" if report.fps else "unknown"
        duration = self._format_duration(report.duration) if report.duration else "unknown"
        return "\n".join(
            [
                path.name,
                verdict,
                f"Видео: {video}",
                f"Звук: {audio}",
                f"Resolution: {resolution}",
                f"FPS: {fps}",
                f"Codecs: {report.video_codec or 'unknown'} / {report.audio_codec or 'unknown'}",
                f"Duration: {duration}",
            ]
        )

    def _handle_finish(self, result: DownloadResult) -> None:
        self.cancel_button.configure(state="disabled")
        self.worker = None

        if result.output_file:
            self.last_output_file = result.output_file
            self.open_folder_button.configure(state="normal")
            if hasattr(self, "open_file_button"):
                self.open_file_button.configure(state="normal")
            if hasattr(self, "copy_path_button"):
                self.copy_path_button.configure(state="normal")

        if result.success:
            self.progress["value"] = 100
            self.percent_var.set("100%")
            self._set_status("Finished")
            if self.active_url:
                self._queue_insert_or_update(self.active_url, status=self.t("done"), progress="100%")
            self._append_log(f"\n{result.message}\n")
            if result.output_file:
                output_files = result.output_files or [result.output_file]
                if len(output_files) == 1:
                    self._append_log(f"Saved file: {result.output_file}\n")
                else:
                    self._append_log(f"Saved files: {len(output_files)}\n")
                    for path in output_files:
                        self._append_log(f"- {path}\n")
                for path in output_files:
                    self._add_history_item(path, self.active_url or "")
                report = probe_media(result.output_file)
                self._append_log("\nПроверка готового файла:\n" + report_to_text(report) + "\n")
                self.result_var.set(self._result_card_text(result.output_file, report))
                if not report.has_video or not report.has_audio:
                    messagebox.showwarning("Проблема в файле", report.message)
            self._append_log(f"Log file: {self.log_file}\n")
            if self.pending_urls:
                if self.queue_paused:
                    self.download_button.configure(text=self.t("resume_queue"), state="normal")
                    self._append_log(f"\nОчередь поставлена на паузу. Осталось: {len(self.pending_urls)}\n")
                    messagebox.showinfo(self.t("queue"), f"Пауза после текущего файла.\nОсталось в очереди: {len(self.pending_urls)}")
                    return
                self._append_log(f"\nОсталось в очереди: {len(self.pending_urls)}\n")
                self._start_next_download()
                return
            self.download_button.configure(state="normal")
            self.queue_paused = False
            self._refresh_pause_button()
            messagebox.showinfo("Finished", "Все загрузки завершены.")
            return

        self.download_button.configure(state="normal")
        if self.active_url:
            self._queue_insert_or_update(self.active_url, status="Ошибка")
            if self.active_url not in self.failed_urls:
                self.failed_urls.append(self.active_url)
        self.pending_urls.clear()
        self.queue_paused = False
        self._refresh_pause_button()
        if self.status_key != "Idle":
            self._set_status("Error")
        self._append_log(f"\n{result.message}\n")
        self._append_log(f"Log file: {self.log_file}\n")
        messagebox.showerror("Download error", result.message)

    def _select_and_probe_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Выбери видео для проверки",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All files", "*.*")],
        )
        if not path:
            return
        self._clear_log()
        self._append_log(f"Проверяю файл:\n{path}\n\n")
        thread = threading.Thread(target=self._probe_file_worker, args=(Path(path),), daemon=True)
        thread.start()

    def _probe_file_worker(self, path: Path) -> None:
        self.event_queue.put(("probe_result", probe_media(path)))

    def _handle_probe_result(self, report: MediaReport) -> None:
        text = report_to_text(report)
        self._append_log(text + "\n")
        self.result_var.set(self._result_card_text(report.path, report))
        if report.compatible:
            messagebox.showinfo("Проверка файла", text)
        else:
            messagebox.showwarning("Проверка файла", text)

    def _select_and_repair_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Выбери видео, которое нужно починить",
            filetypes=[("Video files", "*.mp4 *.mkv *.mov *.webm *.avi"), ("All files", "*.*")],
        )
        if not path:
            return
        self._clear_log()
        self._set_status("Converting")
        self._append_log(f"Чиню видео в универсальный MP4:\n{path}\n\n")
        self.repair_file_button.configure(state="disabled")
        thread = threading.Thread(target=self._repair_file_worker, args=(Path(path),), daemon=True)
        thread.start()

    def _repair_file_worker(self, path: Path) -> None:
        try:
            repaired = repair_to_universal_mp4(path, on_log=lambda line: self.event_queue.put(("log", line)))
            report = probe_media(repaired)
            self.event_queue.put(("repair_result", (True, repaired, report, "")))
        except Exception as exc:
            self.event_queue.put(("repair_result", (False, None, None, str(exc))))

    def _handle_repair_result(self, payload: tuple[bool, Path | None, MediaReport | None, str]) -> None:
        success, repaired, report, error = payload
        self.repair_file_button.configure(state="normal")
        if not success or not repaired:
            self._set_status("Error")
            self._append_log("\nОшибка ремонта:\n" + error + "\n")
            messagebox.showerror(self.t("repair_file"), error)
            return
        self._set_status("Finished")
        self.last_output_file = repaired
        self.open_folder_button.configure(state="normal")
        self._add_history_item(repaired, "")
        self._append_log(f"\nГотовый universal MP4:\n{repaired}\n")
        if report:
            self._append_log("\nПроверка файла после ремонта:\n" + report_to_text(report) + "\n")
            self.result_var.set(self._result_card_text(repaired, report))
        messagebox.showinfo(self.t("repair_file"), f"Готово:\n{repaired}")

    def _start_app_update_check(self) -> None:
        self.check_update_button.configure(state="disabled")
        self._append_log("\nПроверяю обновление приложения через GitHub Releases...\n")
        thread = threading.Thread(target=self._check_app_update_worker, daemon=True)
        thread.start()

    def _check_app_update_worker(self) -> None:
        url = GITHUB_RELEASES.get(platform.system())
        if not url:
            self.event_queue.put(("app_update_result", (False, "Для этой системы автообновление пока не настроено.")))
            return
        try:
            request = urllib.request.Request(url, headers={"User-Agent": APP_TITLE})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.event_queue.put(("app_update_result", (False, f"Не удалось проверить обновления:\n{exc}")))
            return
        latest = str(data.get("tag_name") or data.get("name") or "").lstrip("v")
        page = data.get("html_url") or ""
        if latest and latest != APP_VERSION:
            self.event_queue.put(("app_update_result", (True, f"Доступна версия {latest}.\nОткрой GitHub Releases:\n{page}")))
        else:
            self.event_queue.put(("app_update_result", (True, f"Установлена актуальная версия {APP_VERSION}.")))

    def _handle_app_update_result(self, payload: tuple[bool, str]) -> None:
        success, message = payload
        self.check_update_button.configure(state="normal")
        self._append_log(message + "\n")
        if success:
            messagebox.showinfo("Обновление приложения", message)
        else:
            messagebox.showwarning("Обновление приложения", message)

    def _add_history_item(self, path: Path, url: str) -> None:
        item = {
            "path": str(path),
            "url": url,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.history_items = [entry for entry in self.history_items if entry.get("path") != str(path)]
        self.history_items.insert(0, item)
        self.history_items = self.history_items[:30]
        save_history(self.history_items)
        self._refresh_history()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_listbox"):
            return
        self.history_listbox.delete(0, "end")
        for item in self.history_items[:12]:
            path = Path(item.get("path", ""))
            label = path.name if path.name else item.get("path", "")
            self.history_listbox.insert("end", label)

    def _on_history_select(self, _event: object | None = None) -> None:
        selection = self.history_listbox.curselection()
        if not selection:
            self.selected_history_path = None
            return
        item = self.history_items[selection[0]]
        self.selected_history_path = Path(item.get("path", ""))

    def _open_history_file(self) -> None:
        path = self._current_history_path()
        if path:
            self._open_file(path)

    def _open_history_folder(self) -> None:
        path = self._current_history_path()
        if path:
            open_folder(path.parent)

    def _repeat_history_url(self) -> None:
        selection = self.history_listbox.curselection()
        if not selection:
            messagebox.showwarning(self.t("history"), "Выбери файл в истории.")
            return
        url = self.history_items[selection[0]].get("url", "")
        if not url:
            messagebox.showwarning(self.t("history"), "У этого файла нет сохранённой ссылки.")
            return
        self.url_var.set(url)

    def _current_history_path(self) -> Path | None:
        selection = self.history_listbox.curselection()
        if not selection:
            messagebox.showwarning(self.t("history"), "Выбери файл в истории.")
            return None
        path = Path(self.history_items[selection[0]].get("path", ""))
        if not path.exists():
            messagebox.showwarning(self.t("history"), f"Файл больше не найден:\n{path}")
            return None
        return path

    def _open_file(self, path: Path) -> None:
        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _open_output_folder(self) -> None:
        if self.last_output_file:
            open_folder(self.last_output_file.parent)
        elif self.save_dir_var.get().strip():
            open_folder(Path(self.save_dir_var.get().strip()))

    def _open_last_file(self) -> None:
        if not self.last_output_file or not self.last_output_file.exists():
            messagebox.showwarning(self.t("open_file"), "Файл ещё не выбран или уже удалён.")
            return
        self._open_file(self.last_output_file)

    def _copy_last_file_path(self) -> None:
        if not self.last_output_file:
            messagebox.showwarning(self.t("copy_path"), "Пока нет готового файла.")
            return
        self.clipboard_clear()
        self.clipboard_append(str(self.last_output_file))
        self._append_log(f"Путь скопирован: {self.last_output_file}\n")

    def _open_save_folder(self) -> None:
        path = Path(self.save_dir_var.get().strip()).expanduser() if self.save_dir_var.get().strip() else Path.home()
        path.mkdir(parents=True, exist_ok=True)
        open_folder(path)

    def _open_log_folder(self) -> None:
        open_folder(self.log_file.parent)

    def _copy_log_to_clipboard(self) -> None:
        self.log_text.configure(state="normal")
        text = self.log_text.get("1.0", "end").strip()
        self.log_text.configure(state="disabled")
        if not text and self.log_file.exists():
            try:
                text = self.log_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        if not text:
            messagebox.showinfo(self.t("copy_log"), "Лог пока пустой.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo(self.t("copy_log"), "Лог скопирован в буфер обмена.")

    def _warn_if_external_drive(self, path: Path) -> None:
        if is_probably_external_drive(path):
            messagebox.showwarning(
                "External drive detected",
                "For large videos it is safer to download to local disk first and then copy to the drive.",
            )

    def _save_current_config(self) -> None:
        save_config(
            AppConfig(
                save_directory=self.save_dir_var.get().strip(),
                quality=self.quality_var.get(),
                output_format=self.format_var.get(),
                download_mode=self.mode_var.get(),
                language=self.language_var.get(),
                use_temp_first=self.temp_first_var.get(),
                allow_playlist=self.allow_playlist_var.get(),
                playlist_limit=self._playlist_limit(),
            )
        )

    def _refresh_tool_status(self) -> None:
        yt_dlp = find_executable("yt-dlp")
        ffmpeg = find_executable("ffmpeg")
        if yt_dlp and ffmpeg:
            self.tools_var.set("yt-dlp + ffmpeg ready")
        elif yt_dlp:
            self.tools_var.set("ffmpeg missing")
        elif ffmpeg:
            self.tools_var.set("yt-dlp missing")
        else:
            self.tools_var.set("tools missing")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self._write_log_file(text)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, status: str) -> None:
        self.status_key = status
        self.status_var.set(self._status_label(status))

    def _write_log_file(self, text: str) -> None:
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as file:
                file.write(text)
        except OSError:
            pass


if __name__ == "__main__":
    app = StreamDownloaderApp()
    app.mainloop()
