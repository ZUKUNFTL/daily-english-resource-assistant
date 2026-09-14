from __future__ import annotations

import sys
import traceback
from pathlib import Path


def main() -> None:
    try:
        from daily_english.ui import run

        run()
    except Exception:
        if getattr(sys, "frozen", False):
            log_path = Path(sys.executable).resolve().parent / "startup-error.log"
        else:
            log_path = Path(__file__).resolve().parent / "data" / "startup-error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
