from __future__ import annotations

import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from downloader.config import AppConfig, load_config, save_config
from downloader.core import DownloadRequest, DownloadResult, DownloadWorker, QUALITY_FORMATS
from downloader.utils import (
    check_dependencies,
    dependency_instructions,
    ensure_tool_path,
    find_executable,
    is_probably_external_drive,
    open_folder,
)


APP_TITLE = "ERNI Stream Downloader"
FORMATS = ["MP4", "MKV"]


class StreamDownloaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ensure_tool_path()
        self.title(APP_TITLE)
        self.geometry("980x720")
        self.minsize(860, 620)

        self.config_data = load_config()
        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: DownloadWorker | None = None
        self.last_output_file: Path | None = None

        self.url_var = tk.StringVar()
        self.save_dir_var = tk.StringVar(value=self.config_data.save_directory)
        self.quality_var = tk.StringVar(value=self.config_data.quality)
        self.format_var = tk.StringVar(value=self.config_data.output_format)
        self.temp_first_var = tk.BooleanVar(value=self.config_data.use_temp_first)
        self.status_var = tk.StringVar(value="Idle")
        self.percent_var = tk.StringVar(value="0%")
        self.tools_var = tk.StringVar(value="Checking tools...")

        self._configure_style()
        self._build_ui()
        self._check_dependencies_on_start()
        self.after(100, self._process_events)

    def _configure_style(self) -> None:
        self.configure(bg="#f4f7fb")
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.colors = {
            "bg": "#f4f7fb",
            "panel": "#ffffff",
            "ink": "#172033",
            "muted": "#657085",
            "line": "#d8e0ea",
            "accent": "#2563eb",
            "accent_dark": "#1d4ed8",
            "danger": "#dc2626",
            "success": "#16a34a",
            "log_bg": "#0f172a",
            "log_fg": "#dbeafe",
        }

        self.style.configure("App.TFrame", background=self.colors["bg"])
        self.style.configure("Panel.TFrame", background=self.colors["panel"], relief="flat")
        self.style.configure("Header.TLabel", background=self.colors["bg"], foreground=self.colors["ink"], font=("TkDefaultFont", 24, "bold"))
        self.style.configure("SubHeader.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("TkDefaultFont", 12))
        self.style.configure("SectionTitle.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 13, "bold"))
        self.style.configure("Hint.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("TkDefaultFont", 10))
        self.style.configure("Tool.TLabel", background="#e8f0ff", foreground=self.colors["accent_dark"], font=("TkDefaultFont", 10, "bold"), padding=(10, 5))
        self.style.configure("Field.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Status.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Value.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 11))
        self.style.configure("TEntry", fieldbackground="#ffffff", bordercolor=self.colors["line"], lightcolor=self.colors["line"], darkcolor=self.colors["line"], padding=8)
        self.style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=self.colors["line"], padding=8)
        self.style.configure("TButton", padding=(14, 9), font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Primary.TButton", background=self.colors["accent"], foreground="#ffffff", bordercolor=self.colors["accent"])
        self.style.map("Primary.TButton", background=[("active", self.colors["accent_dark"])], foreground=[("disabled", "#cbd5e1")])
        self.style.configure("Danger.TButton", background=self.colors["danger"], foreground="#ffffff", bordercolor=self.colors["danger"])
        self.style.configure("Card.TLabelframe", background=self.colors["panel"], bordercolor=self.colors["line"], relief="solid")
        self.style.configure("Card.TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        self.style.configure("Horizontal.TProgressbar", troughcolor="#e5eaf2", background=self.colors["accent"], bordercolor="#e5eaf2", lightcolor=self.colors["accent"], darkcolor=self.colors["accent"])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=22, style="App.TFrame")
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Download your own YouTube streams with yt-dlp + ffmpeg, without touching Terminal.",
            style="SubHeader.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        form = ttk.Frame(root, padding=18, style="Panel.TFrame")
        form.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        form.columnconfigure(1, weight=1)

        form_header = ttk.Frame(form, style="Panel.TFrame")
        form_header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        form_header.columnconfigure(0, weight=1)
        ttk.Label(form_header, text="Download setup", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(form_header, textvariable=self.tools_var, style="Tool.TLabel").grid(row=0, column=1, sticky="e")

        ttk.Label(form, text="YouTube URL", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.url_var).grid(row=1, column=1, sticky="ew", padx=10, pady=7, ipady=3)
        ttk.Button(form, text="Paste", command=self._paste_url).grid(row=1, column=2, sticky="ew", pady=7)

        ttk.Label(form, text="Save directory", style="Field.TLabel").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.save_dir_var).grid(row=2, column=1, sticky="ew", padx=10, pady=7, ipady=3)
        ttk.Button(form, text="Browse", command=self._browse_directory).grid(row=2, column=2, sticky="ew", pady=7)

        ttk.Label(form, text="Quality", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=7)
        quality_box = ttk.Combobox(
            form,
            textvariable=self.quality_var,
            values=list(QUALITY_FORMATS.keys()),
            state="readonly",
        )
        quality_box.grid(row=3, column=1, sticky="ew", padx=10, pady=7, ipady=3)

        ttk.Label(form, text="Format", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=7)
        format_box = ttk.Combobox(form, textvariable=self.format_var, values=FORMATS, state="readonly")
        format_box.grid(row=4, column=1, sticky="ew", padx=10, pady=7, ipady=3)

        temp_check = ttk.Checkbutton(
            form,
            text="Download to temporary local folder first, then copy to selected drive",
            variable=self.temp_first_var,
        )
        temp_check.grid(row=5, column=1, sticky="w", padx=10, pady=(10, 4))
        ttk.Label(
            form,
            text="2K mode first requests exact 1440p if YouTube provides it; otherwise it falls back to the best lower quality.",
            style="Hint.TLabel",
        ).grid(row=6, column=1, sticky="w", padx=10, pady=(0, 2))
        ttk.Label(
            form,
            text="Best quality usually downloads video + audio separately, then ffmpeg merges them into one final file.",
            style="Hint.TLabel",
        ).grid(row=7, column=1, sticky="w", padx=10, pady=(0, 6))

        button_row = ttk.Frame(form, style="Panel.TFrame")
        button_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        button_row.columnconfigure(4, weight=1)

        self.download_button = ttk.Button(button_row, text="Download", command=self._start_download, style="Primary.TButton")
        self.download_button.grid(row=0, column=0, padx=(0, 8))

        self.check_quality_button = ttk.Button(button_row, text="Проверить качество", command=self._start_quality_check)
        self.check_quality_button.grid(row=0, column=1, padx=(0, 8))

        self.cancel_button = ttk.Button(button_row, text="Cancel", command=self._cancel_download, state="disabled", style="Danger.TButton")
        self.cancel_button.grid(row=0, column=2, padx=(0, 8))

        self.open_folder_button = ttk.Button(
            button_row,
            text="Open folder",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_folder_button.grid(row=0, column=3, padx=(0, 8))

        status_frame = ttk.Frame(root, padding=16, style="Panel.TFrame")
        status_frame.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        status_frame.columnconfigure(2, weight=1)
        ttk.Label(status_frame, text="Status", style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.status_var, style="Value.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(status_frame, textvariable=self.percent_var, style="Status.TLabel").grid(row=0, column=2, sticky="e")

        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        log_frame = ttk.LabelFrame(root, text="Download log", style="Card.TLabelframe")
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            height=18,
            state="disabled",
            bg=self.colors["log_bg"],
            fg=self.colors["log_fg"],
            insertbackground=self.colors["log_fg"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Menlo", 11) if self.tk.call("tk", "windowingsystem") == "aqua" else ("Consolas", 10),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
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

    def _start_download(self) -> None:
        url = self.url_var.get().strip()
        save_directory = Path(self.save_dir_var.get().strip()).expanduser()

        if not url:
            messagebox.showwarning("Missing URL", "Paste a YouTube URL first.")
            return

        if not self.save_dir_var.get().strip():
            messagebox.showwarning("Missing folder", "Choose a save directory first.")
            return

        ok, missing = check_dependencies()
        if not ok:
            messagebox.showerror("Missing dependencies", dependency_instructions(missing))
            return

        if is_probably_external_drive(save_directory) and not self.temp_first_var.get():
            proceed = messagebox.askyesno(
                "External drive warning",
                "For large videos it is safer to download to local disk first and then copy to the drive.\n\n"
                "You selected an external drive and disabled temporary local download.\n"
                "Do you want to continue anyway?",
            )
            if not proceed:
                return

        self._save_current_config()
        self._clear_log()
        self.progress["value"] = 0
        self.percent_var.set("0%")
        self.last_output_file = None
        self.open_folder_button.configure(state="disabled")

        request = DownloadRequest(
            url=url,
            save_directory=save_directory,
            quality=self.quality_var.get(),
            output_format=self.format_var.get(),
            use_temp_first=self.temp_first_var.get(),
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
        self.status_var.set("Downloading")
        self.worker.start()

    def _start_quality_check(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Paste a YouTube URL first.")
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
        yt_dlp = find_executable("yt-dlp") or "yt-dlp"
        command = [yt_dlp, "-F", "--no-color", url]
        lines: list[str] = []

        self.event_queue.put(("log", "Команда проверки:\n" + " ".join(command) + "\n\n"))
        try:
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
                lines.append(line)
                self.event_queue.put(("log", line))
            return_code = process.wait()
        except Exception as exc:
            self.event_queue.put(("quality_result", (False, f"Не удалось проверить качества:\n{exc}", None, None)))
            return

        output = "".join(lines)
        if return_code != 0:
            self.event_queue.put(("quality_result", (False, "Не удалось прочитать доступные форматы. Посмотри лог.", None, None)))
            return

        max_height = self._max_video_height_from_format_output(output)
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
        self.event_queue.put(("quality_result", (has_1440, message, max_height, recommendation)))

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
        if self.worker:
            self.worker.cancel()
        self.cancel_button.configure(state="disabled")

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
                    self.status_var.set(str(payload))
                elif event == "finish":
                    self._handle_finish(payload)  # type: ignore[arg-type]
                elif event == "quality_result":
                    self._handle_quality_result(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _handle_quality_result(self, payload: tuple[bool, str, int | None, str | None]) -> None:
        has_1440, message, max_height, recommendation = payload
        self.check_quality_button.configure(state="normal")
        self.status_var.set("Idle")
        self._append_log("\nРезультат проверки качества:\n" + message + "\n")
        if max_height:
            self._append_log(f"Максимум найдено: {max_height}p\n")
        if recommendation:
            self._append_log(f"Рекомендация: Quality = {recommendation}\n")
        if has_1440:
            messagebox.showinfo("2K доступен", message)
        else:
            messagebox.showwarning("Рекомендация по качеству", message)

    def _handle_finish(self, result: DownloadResult) -> None:
        self.download_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

        if result.output_file:
            self.last_output_file = result.output_file
            self.open_folder_button.configure(state="normal")

        if result.success:
            self.progress["value"] = 100
            self.percent_var.set("100%")
            self.status_var.set("Finished")
            self._append_log(f"\n{result.message}\n")
            if result.output_file:
                self._append_log(f"Saved file: {result.output_file}\n")
            messagebox.showinfo("Finished", result.message)
            return

        if self.status_var.get() != "Idle":
            self.status_var.set("Error")
        self._append_log(f"\n{result.message}\n")
        messagebox.showerror("Download error", result.message)

    def _open_output_folder(self) -> None:
        if self.last_output_file:
            open_folder(self.last_output_file.parent)
        elif self.save_dir_var.get().strip():
            open_folder(Path(self.save_dir_var.get().strip()))

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

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    app = StreamDownloaderApp()
    app.mainloop()
