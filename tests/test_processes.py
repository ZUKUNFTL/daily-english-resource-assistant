import os
import subprocess

from daily_english.processes import hidden_subprocess_kwargs


def test_child_processes_are_hidden_on_windows() -> None:
    options = hidden_subprocess_kwargs()
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE
    else:
        assert options == {}
