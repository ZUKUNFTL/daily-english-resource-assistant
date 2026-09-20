from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    configured = os.environ.get("TRANSLATION_APP_ROOT")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parents[2]
        if (candidate / "engine").exists():
            return candidate
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _project_root()


def _data_root() -> Path:
    configured = os.environ.get("TRANSLATION_APP_DATA_ROOT")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False) and PROJECT_ROOT == Path(sys.executable).resolve().parent:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "DailyEnglishResourceAssistant"
    return PROJECT_ROOT


DATA_ROOT = _data_root()
APP_DIR = Path(os.environ.get("TRANSLATION_APP_DATA_DIR", DATA_ROOT / "data"))
SETTINGS_PATH = APP_DIR / "settings.json"


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def last_directory(purpose: str = "") -> str:
    """Return the last existing directory used by a picker, with a shared fallback."""
    settings = load_settings()
    keys = [f"last_directory_{purpose}"] if purpose else []
    keys.append("last_directory")
    for key in keys:
        value = settings.get(key, "").strip()
        if value and Path(value).is_dir():
            return value
    return ""


def remember_last_path(selected_path: str | Path, purpose: str = "") -> None:
    """Persist the containing directory for the next file or directory picker."""
    selected = Path(selected_path)
    directory = selected if selected.is_dir() else selected.parent
    if not directory.is_dir():
        return
    value = str(directory.resolve())
    settings = load_settings()
    settings["last_directory"] = value
    if purpose:
        settings[f"last_directory_{purpose}"] = value
    save_settings(settings)


def bool_setting(key: str, default: bool = False) -> bool:
    value = load_settings().get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def set_setting(key: str, value: Any) -> None:
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
