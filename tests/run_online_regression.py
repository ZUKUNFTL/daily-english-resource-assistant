from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from daily_english.downloader import YtDlpDownloader
from daily_english.engine import EngineRunner
from daily_english.models import DownloadStatus, Project
from daily_english.pipeline import CaptionPipeline
from daily_english.providers import BilibiliProvider
from daily_english.subtitles import validate


FIXTURE_ROOT = ROOT / "resources" / "online_regression"
MANIFEST = FIXTURE_ROOT / "online_samples.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regression_error(error: Exception) -> str:
    detail = str(error)
    detail = re.sub(r"[A-Za-z]:\\Users\\[^\\s,]+", "<local-temp>", detail)
    return detail[-2000:]


def find_youtube_url() -> str:
    explicit = os.environ.get("REGRESSION_YOUTUBE_URL", "").strip()
    if explicit:
        return explicit
    try:
        from yt_dlp import YoutubeDL
        options = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "playlistend": 5}
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info("ytsearch5:BBC Learning English short lesson", download=False)
        for item in info.get("entries", []):
            duration = item.get("duration")
            video_id = item.get("id")
            if video_id and duration and 60 <= duration <= 240:
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception as error:
        raise RuntimeError(f"无法搜索英文 YouTube 样本：{error}") from error
    raise RuntimeError("没有找到 1–3 分钟的英文 YouTube 样本，请设置 REGRESSION_YOUTUBE_URL")


def find_bilibili_url() -> str:
    explicit = os.environ.get("REGRESSION_BILIBILI_URL", "").strip()
    if explicit:
        return explicit
    resources = BilibiliProvider().search("中文 英语 学习", limit=10)
    if not resources:
        raise RuntimeError("没有找到公开 B 站样本，请设置 REGRESSION_BILIBILI_URL")
    return resources[0].url


def run_sample(name: str, url: str, source_language: str, target_language: str, media_kind: str) -> dict:
    destination = FIXTURE_ROOT / name
    destination.mkdir(parents=True, exist_ok=True)
    result = YtDlpDownloader().download(url, destination, media_kind)
    project = Project(
        None, result.title, result.author, result.platform, result.url, str(result.path),
        source_language=source_language, target_language=target_language,
        subtitle_order="source_first",
        download_status=DownloadStatus.DOWNLOADED, download_format=media_kind,
    )
    pipeline = CaptionPipeline()
    pipeline.transcribe(project, "small")
    pipeline.translate_missing(project)
    validate(project.captions, require_bilingual=True)
    package = pipeline.export_package(project, destination, create_zip=True)
    srt_path = package / f"{package.name}_中英双语.srt"
    media_path = package / f"{package.name}.mp3"
    return {
        "title": project.title, "source_url": result.url, "platform": result.platform,
        "source_language": project.source_language, "target_language": project.target_language,
        "input_media": str(result.path.relative_to(ROOT)), "input_media_sha256": sha256(result.path),
        "media": str(media_path.relative_to(ROOT)), "media_sha256": sha256(media_path),
        "subtitle": str(srt_path.relative_to(ROOT)), "subtitle_sha256": sha256(srt_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    if os.environ.get("ONLINE_REGRESSION") != "1":
        print("SKIPPED: set ONLINE_REGRESSION=1 to run network downloads")
        return 0
    status = EngineRunner().status()
    if not status.available:
        print(f"SKIPPED: pyVideoTrans sidecar unavailable ({status.message})")
        return 0
    results = []
    samples = [
        ("youtube_english", find_youtube_url, "en", "zh"),
        ("bilibili_chinese", find_bilibili_url, "zh-cn", "en"),
    ]
    media_kind = os.environ.get("REGRESSION_MEDIA_KIND", "audio").strip().lower()
    if media_kind not in {"audio", "video"}:
        print(f"SKIPPED: unsupported REGRESSION_MEDIA_KIND={media_kind}")
        return 0
    for name, url_factory, source_language, target_language in samples:
        try:
            results.append(run_sample(name, url_factory(), source_language, target_language, media_kind))
        except Exception as error:
            results.append({"name": name, "status": "SKIPPED", "error": regression_error(error)})
            print(f"SKIPPED {name}: {error}")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "samples": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
