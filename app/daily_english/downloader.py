from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

import imageio_ffmpeg
import requests


class DownloadError(RuntimeError):
    pass


def ffmpeg_executable() -> Path:
    default_root = Path(__file__).resolve().parents[2]
    if getattr(sys, "frozen", False):
        default_root = Path(sys.executable).resolve().parents[2]
    project_root = Path(os.environ.get("TRANSLATION_APP_ROOT", default_root))
    bundled = project_root / "work" / "tools" / "ffmpeg.exe"
    return bundled if bundled.exists() else Path(imageio_ffmpeg.get_ffmpeg_exe())


ProgressCallback = Callable[[float, str], None]


@dataclass(slots=True)
class DownloadResult:
    title: str
    author: str
    url: str
    platform: str
    path: Path
    duration_seconds: int | None
    media_kind: str


class MediaDownloader(ABC):
    @abstractmethod
    def download(
        self, url: str, destination: str | Path, media_kind: str = "audio",
        progress: ProgressCallback | None = None,
    ) -> DownloadResult: ...


def detect_platform(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
        return "YouTube"
    if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv", "www.b23.tv"}:
        return "Bilibili"
    if host in {"weixin.qq.com", "www.weixin.qq.com", "channels.weixin.qq.com"}:
        return "WeChat Channels"
    return None


def validate_download_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise DownloadError("下载链接必须使用 http 或 https")
    platform = detect_platform(url)
    if platform is None:
        raise DownloadError("只支持 YouTube、B 站和微信视频号链接")
    return url.strip()


def safe_title(title: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", title).strip(" .")
    return cleaned[:180] or "download"


@dataclass(slots=True)
class WeChatChannelsInfo:
    title: str
    author: str
    video_url: str
    cover_url: str


class WeChatChannelsDownloader(MediaDownloader):
    FEED_INFO_API = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
    SPH_PAGE = "https://channels.weixin.qq.com/finder-preview/pages/sph"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    )

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    @staticmethod
    def _short_id(url: str) -> str:
        parsed = urlparse(url)
        match = re.search(r"(?:^|/)sph/([A-Za-z0-9]+)", parsed.path)
        short_id = match.group(1) if match else parse_qs(parsed.query).get("id", [""])[0]
        if not short_id:
            raise DownloadError("无法识别微信视频号分享链接 ID")
        return short_id

    def inspect(self, url: str) -> WeChatChannelsInfo:
        url = validate_download_url(url)
        if detect_platform(url) != "WeChat Channels":
            raise DownloadError("这不是微信视频号链接")
        short_id = self._short_id(url)
        page_url = f"{self.SPH_PAGE}?id={quote(short_id, safe='')}"
        response = self.session.post(
            f"{self.FEED_INFO_API}?_rid={secrets.token_hex(4)}&_pageUrl={quote(self.SPH_PAGE, safe='')}",
            json={"baseReq": {"generalToken": ""}, "shortUri": short_id},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Content-Type": "application/json",
                "Origin": "https://channels.weixin.qq.com",
                "Referer": page_url,
                "User-Agent": self.USER_AGENT,
            },
            timeout=20,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errCode") not in {0, None}:
            raise DownloadError(result.get("errMsg") or "微信视频号接口返回错误")
        data = result.get("data") or {}
        feed = data.get("feedInfo") or {}
        author = data.get("authorInfo") or {}
        video_url = (
            feed.get("videoUrl")
            or (feed.get("h264VideoInfo") or {}).get("videoUrl")
            or (feed.get("h265VideoInfo") or {}).get("videoUrl")
            or ""
        )
        description = (feed.get("description") or "").strip()
        title = (feed.get("title") or (description.splitlines()[0] if description else "")).strip()
        return WeChatChannelsInfo(
            title=title or f"视频号_{short_id}",
            author=(author.get("nickname") or "").strip(),
            video_url=video_url,
            cover_url=feed.get("coverUrl") or "",
        )

    def download(
        self, url: str, destination: str | Path, media_kind: str = "video",
        progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        if media_kind not in {"audio", "video"}:
            raise DownloadError("media_kind 必须是 audio 或 video")
        info = self.inspect(url)
        if not info.video_url:
            raise DownloadError(
                f"已识别视频号作品“{info.title}”（作者：{info.author or '未知'}），"
                "但微信匿名接口未提供媒体流。当前应用不读取账号 Cookie，也不安装抓包证书；"
                "请在获得授权后从微信保存到本地，再从“导入任务”处理。"
            )
        media_host = (urlparse(info.video_url).hostname or "").lower()
        if media_host != "finder.video.qq.com":
            raise DownloadError(f"微信返回了未受信任的媒体主机：{media_host or '空'}")
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        base_path = destination / safe_title(info.title)
        video_path = base_path.with_suffix(".mp4")
        response = self.session.get(
            info.video_url,
            headers={"Referer": f"{self.SPH_PAGE}?id={self._short_id(url)}", "User-Agent": self.USER_AGENT},
            stream=True,
            timeout=(15, 60),
        )
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with video_path.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if progress:
                    percent = downloaded / total * 100 if total else 0.0
                    progress(percent, f"已下载 {downloaded / 1024 / 1024:.1f} MB")
        output_path = video_path
        if media_kind == "audio":
            output_path = base_path.with_suffix(".mp3")
            YtDlpDownloader._convert_media(video_path, output_path, "audio")
        return DownloadResult(
            title=info.title,
            author=info.author,
            url=url,
            platform="WeChat Channels",
            path=output_path,
            duration_seconds=None,
            media_kind=media_kind,
        )


class YtDlpDownloader(MediaDownloader):
    def __init__(self, quiet: bool = True) -> None:
        self.quiet = quiet

    def download(
        self, url: str, destination: str | Path, media_kind: str = "audio",
        progress: ProgressCallback | None = None,
    ) -> DownloadResult:
        url = validate_download_url(url)
        if media_kind not in {"audio", "video"}:
            raise DownloadError("media_kind 必须是 audio 或 video")
        if detect_platform(url) == "WeChat Channels":
            return WeChatChannelsDownloader().download(url, destination, media_kind, progress)
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError as YtDlpError
        except ImportError as error:
            raise DownloadError("未安装 yt-dlp，请运行 python -m pip install yt-dlp==2026.8.19") from error

        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)

        def hook(data: dict) -> None:
            if not progress:
                return
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes", 0)
                percent = float(downloaded) / float(total) * 100 if total else 0.0
                speed = data.get("_speed_str", "")
                eta = data.get("_eta_str", "")
                progress(percent, f"{percent:.1f}%  {speed}  ETA {eta}".strip())
            elif status == "finished":
                progress(100.0, "下载完成，正在整理文件…")

        options = {
            "noplaylist": True,
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noprogress": self.quiet,
            "progress_hooks": [hook],
            "outtmpl": str(destination / "%(title)s.%(ext)s"),
            "restrictfilenames": False,
            "overwrites": False,
            "continuedl": True,
            "retries": 3,
            "ignoreerrors": False,
            "ffmpeg_location": str(ffmpeg_executable()),
        }
        if media_kind == "audio":
            options.update({
                "format": "bestaudio/best",
            })
        else:
            options.update({"format": "bestvideo*+bestaudio/best"})

        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                if info is None:
                    raise DownloadError("平台没有返回媒体信息")
                prepared = Path(downloader.prepare_filename(info))
        except YtDlpError as error:
            raise DownloadError(f"下载失败：{error}") from error

        output_path = prepared
        if not output_path.exists():
            candidates = sorted(
                (path for path in destination.iterdir() if path.is_file() and path.suffix != ".part"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise DownloadError("下载完成但找不到输出文件")
            output_path = candidates[0]
        cleaned_name = safe_title(info.get("title") or output_path.stem)
        desired_suffix = ".mp3" if media_kind == "audio" else ".mp4"
        desired_path = destination / f"{cleaned_name}{desired_suffix}"
        if output_path != desired_path:
            if desired_path.exists():
                output_path = desired_path
            else:
                self._convert_media(output_path, desired_path, media_kind)
                output_path = desired_path
        return DownloadResult(
            title=info.get("title") or output_path.stem,
            author=info.get("uploader") or info.get("channel") or "",
            url=url,
            platform=detect_platform(url) or "未知",
            path=output_path,
            duration_seconds=int(info["duration"]) if info.get("duration") else None,
            media_kind=media_kind,
        )

    @staticmethod
    def _convert_media(source: Path, destination: Path, media_kind: str) -> None:
        ffmpeg = str(ffmpeg_executable())
        if media_kind == "audio":
            command = [ffmpeg, "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-q:a", "3", str(destination)]
        else:
            command = [ffmpeg, "-y", "-i", str(source), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(destination)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode:
            raise DownloadError(f"媒体格式转换失败：{result.stderr[-800:]}")
        if source != destination and source.exists():
            source.unlink()
