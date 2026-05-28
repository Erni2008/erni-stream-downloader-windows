from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


APP_DIR_NAME = "ERNI Stream Downloader"
CONFIG_FILE_NAME = "config.json"


@dataclass
class AppConfig:
    save_directory: str = ""
    quality: str = "1440p / 2K"
    output_format: str = "MP4"
    download_mode: str = "Для VEGAS"
    use_temp_first: bool = True


def get_config_dir() -> Path:
    """Return a per-user config directory that works on macOS and Windows."""
    home = Path.home()

    # Windows normally has APPDATA. Keep a sensible fallback for portable setups.
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME

    if (home / "Library" / "Application Support").exists():
        return home / "Library" / "Application Support" / APP_DIR_NAME

    return home / f".{APP_DIR_NAME.lower().replace(' ', '-')}"


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def get_log_path() -> Path:
    return get_config_dir() / "app.log"


def load_config() -> AppConfig:
    path = get_config_path()
    if not path.exists():
        return AppConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()

    defaults = asdict(AppConfig())
    defaults.update({key: value for key, value in data.items() if key in defaults})
    return AppConfig(**defaults)


def save_config(config: AppConfig) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
