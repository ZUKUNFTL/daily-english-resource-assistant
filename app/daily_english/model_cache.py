from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


SUPPORTED_MODELS = ("small", "medium", "large-v3")
MODEL_REPOSITORIES = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}

_locks_guard = Lock()
_model_locks: dict[str, Lock] = {}

# huggingface_hub reads these settings when it is first imported. Model files
# are large, so the upstream interactive defaults are too short for slow links.
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")


@dataclass(frozen=True, slots=True)
class ModelCacheInfo:
    name: str
    installed: bool
    path: Path | None
    size_bytes: int


def _model_lock(model_name: str) -> Lock:
    with _locks_guard:
        return _model_locks.setdefault(model_name, Lock())


def hub_cache_path(cache_root: str | Path) -> Path:
    return Path(cache_root) / "huggingface" / "hub"


def repository_cache_path(model_name: str, cache_root: str | Path) -> Path:
    repository = MODEL_REPOSITORIES[model_name]
    return hub_cache_path(cache_root) / f"models--{repository.replace('/', '--')}"


def cached_model_path(model_name: str, cache_root: str | Path) -> Path | None:
    from faster_whisper.utils import download_model
    from huggingface_hub.errors import LocalEntryNotFoundError

    hub_cache = hub_cache_path(cache_root)
    try:
        return Path(download_model(model_name, cache_dir=str(hub_cache), local_files_only=True))
    except LocalEntryNotFoundError:
        return None


def model_cache_info(model_name: str, cache_root: str | Path) -> ModelCacheInfo:
    path = cached_model_path(model_name, cache_root)
    size = 0
    if path is not None:
        for file_path in path.rglob("*"):
            if file_path.is_file():
                try:
                    size += file_path.stat().st_size
                except OSError:
                    pass
    return ModelCacheInfo(model_name, path is not None, path, size)


def resolve_faster_whisper_model(model_name: str, cache_root: str | Path, progress=None) -> Path:
    """Resolve locally first and download exactly once per model on a cache miss."""
    from faster_whisper.utils import download_model

    if model_name not in MODEL_REPOSITORIES:
        raise ValueError(f"不支持的模型：{model_name}")
    hub_cache = hub_cache_path(cache_root)
    hub_cache.mkdir(parents=True, exist_ok=True)
    with _model_lock(model_name):
        local_path = cached_model_path(model_name, cache_root)
        if local_path is not None:
            if progress:
                progress(-1.0, f"已找到 {model_name} 模型，正在从本地缓存加载…")
            return local_path
        if progress:
            progress(-1.0, f"本地没有 {model_name} 模型，正在首次下载…")
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return Path(download_model(model_name, cache_dir=str(hub_cache), local_files_only=False))
            except Exception as error:
                last_error = error
                if attempt < 3:
                    if progress:
                        progress(-1.0, f"{model_name} 模型下载连接失败，正在重试（{attempt}/3）…")
                    time.sleep(attempt * 2)
        repository_root = repository_cache_path(model_name, cache_root)
        if repository_root.exists():
            for incomplete in repository_root.rglob("*.incomplete"):
                try:
                    incomplete.unlink()
                except OSError:
                    pass
        raise RuntimeError(
            f"{model_name} 模型首次下载失败（已重试 3 次）：{last_error}\n"
            "请检查当前网络能否访问 huggingface.co，或改用已内置 small 模型的最新版安装包。"
        ) from last_error


def remove_cached_model(model_name: str, cache_root: str | Path) -> bool:
    if model_name not in MODEL_REPOSITORIES:
        raise ValueError(f"不支持的模型：{model_name}")
    repository_root = repository_cache_path(model_name, cache_root)
    with _model_lock(model_name):
        if not repository_root.exists():
            return False
        shutil.rmtree(repository_root)
        return True


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    return f"{size_bytes / 1024:.1f} KB"
