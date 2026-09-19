from __future__ import annotations

import os
import subprocess
from collections.abc import Callable


CancelCallback = Callable[[], bool]


class TaskCancelled(RuntimeError):
    pass


def ensure_not_cancelled(cancel_requested: CancelCallback | None) -> None:
    if cancel_requested and cancel_requested():
        raise TaskCancelled("任务已取消")


def hidden_subprocess_kwargs() -> dict[str, object]:
    """Return platform-safe options that keep child consoles hidden on Windows."""
    if os.name != "nt":
        return {}
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startup_info,
    }
