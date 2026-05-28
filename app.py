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

from downloader.config import AppConfig, get_log_path, load_config, save_config
from downloader.core import DOWNLOAD_MODES, DownloadRequest, DownloadResult, DownloadWorker, QUALITY_FORMATS
from downloader.utils import (
    check_dependencies,
    dependency_instructions,
    ensure_tool_path,
    find_executable,
    get_user_tool_path,
    is_probably_external_drive,
    is_supported_youtube_url,
    open_folder,
)


APP_TITLE = "ERNI Stream Downloader"
APP_VERSION = "1.2.1"
FORMATS = ["MP4", "MKV"]
STATUS_LABELS = {
    "Idle": "Готово",
    "Downloading": "Скачивание",
    "Merging": "Склейка видео и звука",
    "Converting": "Конвертация для MP4/VEGAS",
    "Copying": "Копирование",
    "Finished": "Готово",
    "Error": "Ошибка",
    "Cancelling": "Отмена",
    "Analyzing": "Анализ видео",
}


class StreamDownloaderApp(tk.Tk):
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
        self.queue_urls: list[str] = []
        self.active_url: str | None = None
        self.last_analysis_url: str | None = None
        self.last_analysis_size: int | None = None

        self.url_var = tk.StringVar()
        self.save_dir_var = tk.StringVar(value=self.config_data.save_directory)
        self.quality_var = tk.StringVar(value=self.config_data.quality)
        self.format_var = tk.StringVar(value=self.config_data.output_format)
        self.mode_var = tk.StringVar(value=self.config_data.download_mode)
        self.temp_first_var = tk.BooleanVar(value=self.config_data.use_temp_first)
        self.status_var = tk.StringVar(value=STATUS_LABELS["Idle"])
        self.percent_var = tk.StringVar(value="0%")
        self.tools_var = tk.StringVar(value="Checking tools...")

        self._configure_style()
        self._build_ui()
        self._check_dependencies_on_start()
        self.after(100, self._process_events)

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
            "danger": "#d92d20",
            "success": "#118c4f",
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
        root.rowconfigure(2, weight=1)

        shell = tk.Frame(root, bg=bg)
        shell.grid(row=0, column=0, sticky="nsew", padx=26, pady=22)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        header = tk.Frame(shell, bg="#0f172a", padx=26, pady=22)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text=APP_TITLE, bg="#0f172a", fg="#ffffff", font=("TkDefaultFont", 26, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=f"v{APP_VERSION}", bg="#172338", fg="#dbeafe", padx=12, pady=6, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, sticky="e")
        tk.Label(
            header,
            text="Загрузка, анализ и подготовка YouTube-видео для просмотра, монтажа и VEGAS Pro.",
            bg="#0f172a",
            fg="#b9c6d8",
            font=("TkDefaultFont", 12),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 0))

        main = tk.Frame(shell, bg=bg)
        main.grid(row=1, column=0, sticky="nsew", pady=(18, 14))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)

        form = tk.Frame(main, bg=panel, padx=22, pady=20, highlightthickness=1, highlightbackground="#e1e8f2")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        form.columnconfigure(1, weight=1)

        tk.Label(form, text="Настройка загрузки", bg=panel, fg=ink, font=("TkDefaultFont", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(form, text="Вставь ссылку, выбери режим и запусти очередь.", bg=panel, fg=muted, font=("TkDefaultFont", 10)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 16))

        labels = ["YouTube URL", "Save folder", "Quality", "Format", "Mode"]
        for index, text in enumerate(labels, start=2):
            tk.Label(form, text=text, bg=panel, fg=ink, font=("TkDefaultFont", 10, "bold")).grid(row=index, column=0, sticky="w", pady=8)

        make_entry(form, self.url_var).grid(row=2, column=1, sticky="ew", padx=12, pady=8, ipady=10)
        make_button(form, "Вставить", self._paste_url).grid(row=2, column=2, sticky="ew", pady=8)

        make_entry(form, self.save_dir_var).grid(row=3, column=1, sticky="ew", padx=12, pady=8, ipady=10)
        make_button(form, "Выбрать", self._browse_directory).grid(row=3, column=2, sticky="ew", pady=8)

        quality_box = ttk.Combobox(form, textvariable=self.quality_var, values=list(QUALITY_FORMATS.keys()), state="readonly")
        quality_box.grid(row=4, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        make_button(form, "Анализ", self._start_quality_check).grid(row=4, column=2, sticky="ew", pady=8)

        format_box = ttk.Combobox(form, textvariable=self.format_var, values=FORMATS, state="readonly")
        format_box.grid(row=5, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        tk.Label(form, text="MP4 подходит для плееров и монтажа", bg=panel, fg=muted, font=("TkDefaultFont", 9)).grid(row=5, column=2, sticky="w", padx=(0, 4))

        mode_box = ttk.Combobox(form, textvariable=self.mode_var, values=DOWNLOAD_MODES, state="readonly")
        mode_box.grid(row=6, column=1, sticky="ew", padx=12, pady=8, ipady=6)
        tk.Label(form, text="VEGAS = H.264/AAC/CFR", bg=panel, fg=muted, font=("TkDefaultFont", 9)).grid(row=6, column=2, sticky="w", padx=(0, 4))

        option_box = tk.Frame(form, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        option_box.grid(row=7, column=1, columnspan=2, sticky="ew", padx=12, pady=(12, 4))
        tk.Checkbutton(
            option_box,
            text="Сначала скачать локально, потом скопировать в выбранную папку",
            variable=self.temp_first_var,
            bg=soft,
            fg=ink,
            activebackground=soft,
            selectcolor="#ffffff",
            font=("TkDefaultFont", 10, "bold"),
            relief="flat",
            bd=0,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(option_box, text="Лучше для больших файлов, флешек и внешних дисков.", bg=soft, fg=muted, font=("TkDefaultFont", 9)).grid(row=1, column=0, sticky="w", pady=(4, 0))

        action_row = tk.Frame(form, bg=panel)
        action_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(18, 0))
        action_row.columnconfigure(5, weight=1)
        self.download_button = make_button(action_row, "Скачать", self._start_download, "primary")
        self.download_button.grid(row=0, column=0, padx=(0, 8))
        self.check_quality_button = make_button(action_row, "Анализ видео", self._start_quality_check)
        self.check_quality_button.grid(row=0, column=1, padx=(0, 8))
        self.cancel_button = make_button(action_row, "Отмена", self._cancel_download, "danger", state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=(0, 8))
        self.open_folder_button = make_button(action_row, "Папка", self._open_output_folder, state="disabled")
        self.open_folder_button.grid(row=0, column=3, padx=(0, 8))
        self.update_ytdlp_button = make_button(action_row, "Обновить yt-dlp", self._start_update_ytdlp)
        self.update_ytdlp_button.grid(row=0, column=4, padx=(0, 8))
        self.open_log_button = make_button(action_row, "Лог", self._open_log_folder, "ghost")
        self.open_log_button.grid(row=0, column=5, sticky="e")

        side = tk.Frame(main, bg=panel, padx=18, pady=18, highlightthickness=1, highlightbackground="#e1e8f2")
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        tk.Label(side, textvariable=self.tools_var, bg="#e8f1ff", fg="#185abc", padx=12, pady=8, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="ew")
        tk.Label(side, text="Очередь", bg=panel, fg=ink, font=("TkDefaultFont", 16, "bold")).grid(row=1, column=0, sticky="w", pady=(18, 6))
        tk.Label(side, text="Добавляй несколько ссылок и скачивай подряд.", bg=panel, fg=muted, wraplength=260, justify="left", font=("TkDefaultFont", 10)).grid(row=2, column=0, sticky="w")
        self.queue_listbox = tk.Listbox(
            side,
            height=7,
            bg="#f8fafc",
            fg=ink,
            selectbackground=accent,
            relief="flat",
            highlightthickness=1,
            highlightbackground="#d9e2ef",
            font=("TkDefaultFont", 10),
        )
        self.queue_listbox.grid(row=3, column=0, sticky="ew", pady=(12, 10))
        queue_buttons = tk.Frame(side, bg=panel)
        queue_buttons.grid(row=4, column=0, sticky="ew")
        queue_buttons.columnconfigure((0, 1, 2), weight=1)
        make_button(queue_buttons, "+", self._add_url_to_queue, "secondary").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        make_button(queue_buttons, "Удалить", self._remove_selected_queue_item, "secondary").grid(row=0, column=1, sticky="ew", padx=(0, 6))
        make_button(queue_buttons, "Очистить", self._clear_queue_items, "secondary").grid(row=0, column=2, sticky="ew")

        tips = tk.Frame(side, bg=soft, padx=14, pady=12, highlightthickness=1, highlightbackground="#e8eef7")
        tips.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        tk.Label(tips, text="Как качает", bg=soft, fg=ink, font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            tips,
            text="В высоком качестве YouTube часто отдаёт видео и звук отдельно. Приложение скачивает оба потока и собирает итоговый файл через ffmpeg.",
            bg=soft,
            fg=muted,
            wraplength=270,
            justify="left",
            font=("TkDefaultFont", 9),
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        status_frame = tk.Frame(shell, bg=panel, padx=18, pady=16, highlightthickness=1, highlightbackground="#e1e8f2")
        status_frame.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        status_frame.columnconfigure(0, weight=1)
        status_frame.columnconfigure(1, weight=1)
        tk.Label(status_frame, text="СТАТУС", bg=panel, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(status_frame, text="ПРОГРЕСС", bg=panel, fg=muted, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(18, 0))
        tk.Label(status_frame, textvariable=self.status_var, bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 0))
        tk.Label(status_frame, textvariable=self.percent_var, bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=1, column=1, sticky="w", padx=(18, 0), pady=(4, 0))
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        log_panel = tk.Frame(shell, bg=panel, padx=16, pady=14, highlightthickness=1, highlightbackground="#e1e8f2")
        log_panel.grid(row=3, column=0, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(1, weight=1)
        shell.rowconfigure(3, weight=1)
        tk.Label(log_panel, text="Журнал загрузки", bg=panel, fg=ink, font=("TkDefaultFont", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
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
        self._refresh_tool_status()

    def _check_dependencies_on_start(self) -> None:
        ok, missing = check_dependencies()
        self._refresh_tool_status()
        if ok:
            return
        messagebox.showerror("Missing dependencies", dependency_instructions(missing))
        self._append_log(dependency_instructions(missing) + "\n")

    def _paste_url(self) -> None:
        try:
            self.url_var.set(self.clipboard_get().strip())
        except tk.TclError:
            messagebox.showwarning("Clipboard", "Clipboard is empty or does not contain text.")

    def _browse_directory(self) -> None:
        initial = self.save_dir_var.get() or str(Path.home())
        directory = filedialog.askdirectory(initialdir=initial)
        if directory:
            self.save_dir_var.set(directory)
            self._warn_if_external_drive(Path(directory))

    def _add_url_to_queue(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Очередь", "Сначала вставь YouTube-ссылку.")
            return
        if not is_supported_youtube_url(url):
            messagebox.showwarning("Очередь", "Это не похоже на YouTube-ссылку.")
            return
        if url in self.queue_urls:
            messagebox.showinfo("Очередь", "Эта ссылка уже есть в очереди.")
            return
        self.queue_urls.append(url)
        self.queue_listbox.insert("end", url)
        self.url_var.set("")

    def _remove_selected_queue_item(self) -> None:
        selected = list(self.queue_listbox.curselection())
        for index in reversed(selected):
            self.queue_listbox.delete(index)
            del self.queue_urls[index]

    def _clear_queue_items(self) -> None:
        self.queue_urls.clear()
        self.queue_listbox.delete(0, "end")

    def _start_download(self) -> None:
        urls = self._collect_download_urls()
        if not urls:
            return
        self.pending_urls = urls
        self._clear_queue_items()
        self._clear_log()
        self._write_log_file(
            f"\n=== {APP_TITLE} {APP_VERSION} session {datetime.now().isoformat(timespec='seconds')} ===\n"
            f"Queue size: {len(self.pending_urls)}\n"
            f"Save directory: {Path(self.save_dir_var.get().strip()).expanduser()}\n"
            f"Quality: {self.quality_var.get()}\n"
            f"Format: {self.format_var.get()}\n"
            f"Mode: {self.mode_var.get()}\n"
            f"Temp first: {self.temp_first_var.get()}\n\n"
        )
        self._start_next_download()

    def _collect_download_urls(self) -> list[str] | None:
        urls = list(self.queue_urls)
        typed_url = self.url_var.get().strip()
        if typed_url and typed_url not in urls:
            urls.insert(0, typed_url)

        if not urls:
            messagebox.showwarning("Missing URL", "Paste a YouTube URL first.")
            return None

        invalid = [url for url in urls if not is_supported_youtube_url(url)]
        if invalid:
            messagebox.showwarning(
                "Unsupported URL",
                "В очереди есть ссылка, которая не похожа на YouTube:\n" + invalid[0],
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

        self._save_current_config()
        return urls

    def _start_next_download(self) -> None:
        if not self.pending_urls:
            self.download_button.configure(state="normal")
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
        self._append_log(f"\n--- Новая загрузка ---\nURL: {url}\n")
        analysis = self._analyze_video_sync(url)
        estimated_size = None
        if analysis:
            estimated_size = analysis.get("estimated_size")
            self.last_analysis_url = url
            self.last_analysis_size = estimated_size
            self._append_log(self._analysis_message(analysis) + "\n")
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

    def _start_quality_check(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a YouTube URL first.")
            return
        if not is_supported_youtube_url(url):
            messagebox.showwarning("Unsupported URL", "Please paste a valid YouTube URL.")
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
        self._append_log("Проверяю доступные качества на YouTube...\n\n")

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
        fps_values: list[float] = []
        known_sizes: list[int] = []
        for item in formats:
            if not isinstance(item, dict):
                continue
            height = item.get("height")
            if isinstance(height, int) and 200 <= height <= 5000:
                heights.append(height)
            fps = item.get("fps")
            if isinstance(fps, (int, float)) and fps > 0:
                fps_values.append(float(fps))
            size = item.get("filesize") or item.get("filesize_approx")
            if isinstance(size, int) and size > 0:
                known_sizes.append(size)

        top_size = info.get("filesize") or info.get("filesize_approx")
        if isinstance(top_size, int) and top_size > 0:
            known_sizes.append(top_size)

        estimated_size = max(known_sizes) if known_sizes else None
        return {
            "title": info.get("title") or "Unknown title",
            "duration": info.get("duration"),
            "max_height": max(heights) if heights else None,
            "max_fps": max(fps_values) if fps_values else None,
            "estimated_size": estimated_size,
            "format_count": len(formats),
        }

    def _analysis_message(self, analysis: dict[str, object]) -> str:
        title = analysis.get("title") or "Unknown title"
        max_height = analysis.get("max_height")
        max_fps = analysis.get("max_fps")
        estimated_size = analysis.get("estimated_size")
        duration = analysis.get("duration")
        recommendation = self._recommended_quality_for_height(max_height if isinstance(max_height, int) else None)
        lines = [
            "Автоанализ видео:",
            f"Название: {title}",
            f"Максимальное качество: {max_height}p" if max_height else "Максимальное качество: не удалось определить",
            f"FPS: {max_fps:g}" if isinstance(max_fps, float) else "FPS: не удалось определить",
            f"Примерный размер: {self._format_bytes(estimated_size)}" if isinstance(estimated_size, int) else "Примерный размер: не удалось определить",
            f"Длительность: {self._format_duration(duration)}" if isinstance(duration, (int, float)) else "Длительность: не удалось определить",
            f"Рекомендация: Quality = {recommendation}",
        ]
        return "\n".join(lines)

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
                elif event == "status":
                    self._set_status(str(payload))
                elif event == "finish":
                    self._handle_finish(payload)  # type: ignore[arg-type]
                elif event == "quality_result":
                    self._handle_quality_result(payload)  # type: ignore[arg-type]
                elif event == "update_ytdlp_result":
                    self._handle_update_ytdlp_result(payload)  # type: ignore[arg-type]
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
            self._append_log("\n" + self._analysis_message(analysis) + "\n")
        if max_height:
            self._append_log(f"Максимум найдено: {max_height}p\n")
        if recommendation:
            self._append_log(f"Рекомендация: Quality = {recommendation}\n")
        if has_1440:
            messagebox.showinfo("2K доступен", message)
        else:
            messagebox.showwarning("Рекомендация по качеству", message)

    def _handle_finish(self, result: DownloadResult) -> None:
        self.cancel_button.configure(state="disabled")

        if result.output_file:
            self.last_output_file = result.output_file
            self.open_folder_button.configure(state="normal")

        if result.success:
            self.progress["value"] = 100
            self.percent_var.set("100%")
            self._set_status("Finished")
            self._append_log(f"\n{result.message}\n")
            if result.output_file:
                self._append_log(f"Saved file: {result.output_file}\n")
            self._append_log(f"Log file: {self.log_file}\n")
            if self.pending_urls:
                self._append_log(f"\nОсталось в очереди: {len(self.pending_urls)}\n")
                self._start_next_download()
                return
            self.download_button.configure(state="normal")
            messagebox.showinfo("Finished", "Все загрузки завершены.")
            return

        self.download_button.configure(state="normal")
        self.pending_urls.clear()
        if self.status_var.get() != STATUS_LABELS["Idle"]:
            self._set_status("Error")
        self._append_log(f"\n{result.message}\n")
        self._append_log(f"Log file: {self.log_file}\n")
        messagebox.showerror("Download error", result.message)

    def _open_output_folder(self) -> None:
        if self.last_output_file:
            open_folder(self.last_output_file.parent)
        elif self.save_dir_var.get().strip():
            open_folder(Path(self.save_dir_var.get().strip()))

    def _open_log_folder(self) -> None:
        open_folder(self.log_file.parent)

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
                use_temp_first=self.temp_first_var.get(),
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
        self.status_var.set(STATUS_LABELS.get(status, status))

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
