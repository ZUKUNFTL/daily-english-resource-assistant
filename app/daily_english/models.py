from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProjectStatus(StrEnum):
    PENDING = "待处理"
    PROCESSING = "处理中"
    REVIEW = "待检查"
    EXPORTED = "已导出"
    UPLOADED = "已上传"
    FAILED = "失败"
    CANCELLED = "已取消"


class DownloadStatus(StrEnum):
    PENDING = "待下载"
    DOWNLOADING = "下载中"
    DOWNLOADED = "已下载"
    FAILED = "下载失败"


@dataclass(slots=True)
class Resource:
    provider: str
    title: str
    url: str
    author: str = ""
    duration_seconds: int | None = None
    language: str = "English"
    captions: str = "未知"
    license_note: str = "仅供发现；请确认使用授权。"
    download_url: str = ""
    download_status: DownloadStatus = DownloadStatus.PENDING
    local_media_path: str = ""


@dataclass(slots=True)
class Caption:
    start: float
    end: float
    source_text: str
    translated_text: str = ""

    @property
    def english(self) -> str:
        return self.source_text

    @english.setter
    def english(self, value: str) -> None:
        self.source_text = value

    @property
    def chinese(self) -> str:
        return self.translated_text

    @chinese.setter
    def chinese(self, value: str) -> None:
        self.translated_text = value


@dataclass(slots=True)
class Project:
    id: int | None
    title: str
    author: str = ""
    provider: str = "本地导入"
    source_url: str = ""
    media_path: str = ""
    reference_path: str = ""
    subtitle_source: str = ""
    status: ProjectStatus = ProjectStatus.PENDING
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    captions: list[Caption] = field(default_factory=list)
    source_language: str = "auto"
    target_language: str = "zh"
    subtitle_order: str = "source_first"
    recognition_engine: str = "faster-whisper"
    translation_engine: str = "pyvideotrans-local"
    alignment_enabled: bool = False
    download_status: DownloadStatus = DownloadStatus.PENDING
    download_format: str = "audio"
