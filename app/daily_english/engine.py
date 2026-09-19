from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

import imageio_ffmpeg

from .models import Caption
from .processes import hidden_subprocess_kwargs
from .settings import DATA_ROOT, PROJECT_ROOT
from .subtitles import read_srt


ProgressCallback = Callable[[float, str], None]


class EngineUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class EngineStatus:
    available: bool
    python_path: str
    cli_path: str
    version: str
    message: str


class EngineRunner:
    """Run pyVideoTrans as an isolated Python 3.10 sidecar process."""

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.root = Path(project_root or os.environ.get("TRANSLATION_APP_ROOT", PROJECT_ROOT))
        self.data_root = Path(
            self.root if project_root is not None
            else os.environ.get("TRANSLATION_APP_DATA_ROOT", DATA_ROOT)
        )
        self.engine_root = self.root / "engine" / "pyvideotrans"
        self.manifest_path = self.root / "engine" / "pyvideotrans.lock.json"

    @property
    def cache_root(self) -> Path:
        return self.data_root / "work" / "cache"

    @property
    def temporary_root(self) -> Path:
        return self.data_root / "work" / "tmp"

    @property
    def python_path(self) -> Path:
        if os.name == "nt":
            return self.engine_root / ".venv" / "Scripts" / "python.exe"
        return self.engine_root / ".venv" / "bin" / "python"

    @property
    def cli_path(self) -> Path:
        return self.engine_root / "source" / "cli.py"

    def status(self) -> EngineStatus:
        version = ""
        if self.manifest_path.exists():
            try:
                version = json.loads(self.manifest_path.read_text(encoding="utf-8")).get("version", "")
            except json.JSONDecodeError:
                version = ""
        available = self.python_path.exists() and self.cli_path.exists()
        if available:
            message = "当前使用 pyVideoTrans sidecar（支持 WhisperX/词级对齐）"
        elif getattr(sys, "frozen", False):
            message = (
                "当前使用内置 faster-whisper + Argos Translate，可直接转写并生成双语字幕；"
                "WhisperX/词级对齐属于可选增强，当前未安装。"
            )
        else:
            message = (
                "当前使用内置 faster-whisper + Argos Translate，可直接转写并生成双语字幕；"
                "如需 WhisperX/词级对齐，可运行 engine/setup_sidecar.ps1 安装可选 sidecar。"
            )
        return EngineStatus(available, str(self.python_path), str(self.cli_path), version, message)

    def _require(self) -> None:
        status = self.status()
        if not status.available:
            raise EngineUnavailable(status.message)

    def run_stt(
        self, media_path: str | Path, source_language: str = "auto", model_name: str = "small",
        alignment_enabled: bool = False, progress: ProgressCallback | None = None,
    ) -> list[Caption]:
        self._require()
        language = source_language if source_language != "auto" else "auto"
        with self._temporary_directory("daily-english-stt-") as directory:
            self._run(
                ["--task", "stt", "--name", str(media_path), "--output-dir", directory,
                 "--detect_language", language, "--model_name", model_name, "--fix_punc"],
                directory,
                progress,
            )
            subtitle_path = self._find_srt(directory)
            captions = read_srt(subtitle_path, bilingual=False)
            if alignment_enabled:
                # pyVideoTrans selects WhisperX when its provider is configured; the
                # flag is kept in metadata even when the sidecar falls back to STT.
                pass
            return captions

    def run_sts(
        self, subtitle_path: str | Path, source_language: str, target_language: str,
        progress: ProgressCallback | None = None,
    ) -> list[Caption]:
        self._require()
        with self._temporary_directory("daily-english-sts-") as directory:
            self._run(
                ["--task", "sts", "--name", str(subtitle_path), "--output-dir", directory,
                 "--source_language_code", source_language, "--target_language_code", target_language],
                directory,
                progress,
            )
            return read_srt(self._find_srt(directory), bilingual=False)

    def _temporary_directory(self, prefix: str) -> TemporaryDirectory:
        directory = self.temporary_root
        directory.mkdir(parents=True, exist_ok=True)
        return TemporaryDirectory(prefix=prefix, dir=directory)

    def _run(
        self, arguments: list[str], output_directory: str,
        progress: ProgressCallback | None = None,
    ) -> None:
        command = [str(self.python_path), str(self.cli_path), *arguments]
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        cache_root = self.cache_root
        cache_root.mkdir(parents=True, exist_ok=True)
        environment["HF_HOME"] = str(cache_root / "huggingface")
        environment["HUGGINGFACE_HUB_CACHE"] = str(cache_root / "huggingface" / "hub")
        environment["TRANSFORMERS_CACHE"] = str(cache_root / "huggingface" / "transformers")
        environment["TORCH_HOME"] = str(cache_root / "torch")
        environment["XDG_CACHE_HOME"] = str(cache_root)
        environment["TEMP"] = str(self.temporary_root)
        environment["TMP"] = str(self.temporary_root)
        Path(environment["TEMP"]).mkdir(parents=True, exist_ok=True)
        Path(environment["TMP"]).mkdir(parents=True, exist_ok=True)
        bundled_ffmpeg = self.data_root / "work" / "tools" / "ffmpeg.exe"
        ffmpeg_directory = str(bundled_ffmpeg.parent) if bundled_ffmpeg.exists() else str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
        environment["PATH"] = ffmpeg_directory + os.pathsep + environment.get("PATH", "")
        output_lines: list[str] = []
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", env=environment, bufsize=1,
                **hidden_subprocess_kwargs(),
            )
        except OSError as error:
            raise RuntimeError(f"无法启动 pyVideoTrans：{error}") from error
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            output_lines.append(line)
            if len(output_lines) > 200:
                output_lines.pop(0)
            if progress:
                percent, message = self._progress_from_line(line)
                if message:
                    try:
                        progress(percent, message)
                    except Exception:
                        pass
        return_code = process.wait()
        if return_code:
            detail = "\n".join(output_lines)[-2000:]
            raise RuntimeError(f"pyVideoTrans 执行失败（{return_code}）：{detail}")

    @staticmethod
    def _progress_from_line(line: str) -> tuple[float, str]:
        stt_match = re.search(r"\[STT_PROGRESS\]\s*(\d+(?:\.\d+)?)%?", line)
        if stt_match:
            raw_percent = min(100.0, float(stt_match.group(1)))
            return 25.0 + raw_percent * 0.60, f"正在转写 {raw_percent:.1f}%"
        percent_match = re.search(r"(\d+(?:\.\d+)?)%", line)
        if percent_match and any(word in line.lower() for word in ("download", "下载")):
            raw_percent = min(100.0, float(percent_match.group(1)))
            return 3.0 + raw_percent * 0.20, f"正在下载模型 {raw_percent:.1f}%"
        lowered = line.lower()
        if "loading " in lowered or "model:" in lowered:
            return 25.0, line
        if "transcribe" in lowered or "stt starting" in lowered:
            return 30.0, "模型已加载，正在分析音频…"
        if "[done]" in lowered or "[完成]" in line:
            return 85.0, "语音转写完成"
        return -1.0, line

    @staticmethod
    def _find_srt(directory: str | Path) -> Path:
        paths = sorted(Path(directory).rglob("*.srt"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not paths:
            raise RuntimeError("pyVideoTrans 未生成 SRT 文件")
        return paths[0]
