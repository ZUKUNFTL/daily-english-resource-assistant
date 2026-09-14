from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _project_root() -> Path:
    configured = os.environ.get("TRANSLATION_APP_ROOT")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parents[2]
        if (candidate / "engine").exists():
            return candidate
    return Path(__file__).resolve().parents[2]


APP_DIR = Path(os.environ.get("TRANSLATION_APP_DATA_DIR", _project_root() / "data"))
SETTINGS_PATH = APP_DIR / "settings.json"


def load_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict[str, str]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
