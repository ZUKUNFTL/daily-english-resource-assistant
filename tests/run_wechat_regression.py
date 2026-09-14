from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from daily_english.downloader import DownloadError, WeChatChannelsDownloader


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if os.environ.get("ONLINE_REGRESSION") != "1":
        print("SKIPPED: set ONLINE_REGRESSION=1 to inspect a WeChat Channels link")
        return 0
    url = os.environ.get("REGRESSION_WECHAT_URL", "https://weixin.qq.com/sph/A1sNLfChlV")
    short_id = url.rstrip("/").split("/")[-1].split("?")[0]
    destination = ROOT / "resources" / "wechat_channels" / short_id
    destination.mkdir(parents=True, exist_ok=True)
    downloader = WeChatChannelsDownloader()
    info = downloader.inspect(url)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url,
        "platform": "WeChat Channels",
        "title": info.title,
        "author": info.author,
        "cover_url": info.cover_url,
        "anonymous_media_available": bool(info.video_url),
        "security_policy": "No cookies, login sessions, proxy interception, or certificate installation.",
    }
    try:
        result = downloader.download(url, destination, "video")
        report.update({
            "status": "DOWNLOADED",
            "media_path": str(result.path),
            "media_sha256": sha256(result.path),
        })
    except DownloadError as error:
        report.update({"status": "SKIPPED_AUTHORIZATION_REQUIRED", "message": str(error)})
    report_path = destination / "inspection.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
