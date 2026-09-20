from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable
from zipfile import ZIP_DEFLATED, ZipFile

import imageio_ffmpeg

from .models import Caption, Project, ProjectStatus
from .model_cache import resolve_faster_whisper_model
from .processes import CancelCallback, ensure_not_cancelled, hidden_subprocess_kwargs
from .references import read_reference_text, whisper_reference_prompt
from .subtitles import read_srt, write_srt
from .engine import EngineRunner, EngineUnavailable


ProgressCallback = Callable[[float, str], None]


class TranslationUnavailable(RuntimeError):
    pass


class LocalTranslator:
    """Extension point for an installed offline English-to-Chinese model."""

    def translate(self, texts: list[str]) -> list[str]:
        raise TranslationUnavailable(
            "未配置离线英译中模型。请导入已有中英 SRT，或安装并启用翻译提供方后再处理。"
        )


class PyVideoTransTranslator(LocalTranslator):
    def __init__(self, runner: EngineRunner, source_language: str, target_language: str) -> None:
        self.runner = runner
        self.source_language = source_language
        self.target_language = target_language

    def translate(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        temp_root = self.runner.temporary_root
        temp_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="daily-english-translate-", dir=temp_root) as directory:
            source_path = Path(directory) / "source.srt"
            write_srt(
                [Caption(index * 2, index * 2 + 1, text) for index, text in enumerate(texts)],
                source_path,
                require_bilingual=False,
            )
            translated = self.runner.run_sts(source_path, self.source_language, self.target_language)
            return [caption.source_text for caption in translated]


class ArgosTranslator(LocalTranslator):
    def __init__(
        self, root: str | Path, source_language: str, target_language: str,
        data_root: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.data_root = Path(data_root or root)
        self.source_language = source_language
        self.target_language = target_language
        self.engine_root = self.root / "engine" / "argos_translate"

    @property
    def python_path(self) -> Path:
        if os.name == "nt":
            return self.engine_root / ".venv" / "Scripts" / "python.exe"
        return self.engine_root / ".venv" / "bin" / "python"

    @property
    def script_path(self) -> Path:
        return self.engine_root / "translate.py"

    @property
    def executable_path(self) -> Path:
        return self.engine_root / "argos_translate.exe"

    def available(self) -> bool:
        package_root = self.data_root / "work" / "models" / "argos"
        if not package_root.exists():
            return False
        runtime_available = self.executable_path.exists() or (
            self.python_path.exists() and self.script_path.exists()
        )
        return runtime_available and any(package_root.iterdir())

    def translate(self, texts: list[str]) -> list[str]:
        if not self.available():
            raise TranslationUnavailable("未安装 Argos 中英离线翻译模型；请运行 engine/setup_argos.ps1。")
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        environment["XDG_DATA_HOME"] = str(self.data_root / "work" / "data")
        environment["XDG_CONFIG_HOME"] = str(self.data_root / "work" / "config")
        environment["XDG_CACHE_HOME"] = str(self.data_root / "work" / "cache")
        environment["ARGOS_PACKAGES_DIR"] = str(self.data_root / "work" / "models" / "argos")
        environment["ARGOS_DEVICE_TYPE"] = "cpu"
        environment["ARGOS_CHUNK_TYPE"] = "MINISBD"
        request = json.dumps(
            {"source_language": self.source_language, "target_language": self.target_language, "texts": texts},
            ensure_ascii=False,
        )
        command = (
            [str(self.executable_path)] if self.executable_path.exists()
            else [str(self.python_path), str(self.script_path)]
        )
        result = subprocess.run(
            command, input=request, capture_output=True,
            text=True, encoding="utf-8", errors="replace", env=environment,
            **hidden_subprocess_kwargs(),
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            raise RuntimeError(f"Argos 离线翻译失败：{detail}")
        translations = json.loads(result.stdout).get("translations", [])
        if len(translations) != len(texts):
            raise RuntimeError("Argos 离线翻译返回的字幕数量不匹配")
        return translations


class CaptionPipeline:
    def __init__(self, translator: LocalTranslator | None = None, runner: EngineRunner | None = None) -> None:
        self.runner = runner or EngineRunner()
        self.translator = translator

    def import_srt(self, project: Project, subtitle_path: str) -> Project:
        project.captions = read_srt(subtitle_path)
        project.subtitle_source = "用户导入 SRT"
        project.status = ProjectStatus.REVIEW
        return project

    def transcribe(
        self, project: Project, model_name: str = "small",
        progress: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> Project:
        ensure_not_cancelled(cancel_requested)
        if not project.media_path:
            raise ValueError("请先选择本地音频或视频文件")
        if progress:
            progress(1.0, f"准备加载 {model_name} 模型…")
        reference_prompt = ""
        if project.reference_path:
            if progress:
                progress(2.0, "正在读取参考文稿…")
            reference_prompt = whisper_reference_prompt(read_reference_text(project.reference_path))
            ensure_not_cancelled(cancel_requested)
        if self.runner.status().available and not reference_prompt:
            project.captions = self.runner.run_stt(
                project.media_path, project.source_language, model_name, project.alignment_enabled,
                progress,
            )
            if project.source_language == "auto":
                project.source_language = "zh-cn" if any("\u4e00" <= char <= "\u9fff" for caption in project.captions for char in caption.source_text) else "en"
                if project.source_language.startswith("zh") and project.target_language == "zh":
                    project.target_language = "en"
                    project.subtitle_order = "source_first"
                elif project.source_language == "en" and project.target_language == "en":
                    project.target_language = "zh"
            project.recognition_engine = "pyVideoTrans"
            project.subtitle_source = f"pyVideoTrans {model_name} 转写"
            project.status = ProjectStatus.REVIEW
            return project
        from faster_whisper import WhisperModel

        cache_root = self.runner.cache_root
        temp_root = self.runner.temporary_root
        cache_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(cache_root / "huggingface")
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(cache_root / "huggingface" / "hub")
        os.environ["TRANSFORMERS_CACHE"] = str(cache_root / "huggingface" / "transformers")
        os.environ["TORCH_HOME"] = str(cache_root / "torch")
        os.environ["XDG_CACHE_HOME"] = str(cache_root)
        os.environ["TEMP"] = str(temp_root)
        os.environ["TMP"] = str(temp_root)
        ffmpeg_directory = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
        os.environ["PATH"] = ffmpeg_directory + os.pathsep + os.environ.get("PATH", "")
        model_path = resolve_faster_whisper_model(model_name, cache_root, progress)
        ensure_not_cancelled(cancel_requested)
        model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
        ensure_not_cancelled(cancel_requested)
        language = None if project.source_language == "auto" else project.source_language.split("-")[0]
        segments, info = model.transcribe(
            project.media_path, language=language, beam_size=5, vad_filter=True, word_timestamps=True,
            initial_prompt=reference_prompt or None,
        )
        captions = []
        duration = max(float(getattr(info, "duration", 0.0) or 0.0), 0.001)
        for segment in segments:
            ensure_not_cancelled(cancel_requested)
            if segment.text.strip():
                captions.append(Caption(segment.start, segment.end, segment.text.strip()))
            if progress:
                raw_percent = min(100.0, float(segment.end) / duration * 100.0)
                progress(25.0 + raw_percent * 0.60, f"正在转写 {raw_percent:.1f}%")
        project.captions = captions
        if project.source_language == "auto":
            project.source_language = info.language or "en"
            if project.source_language.startswith("zh") and project.target_language == "zh":
                project.target_language = "en"
                project.subtitle_order = "source_first"
            elif project.source_language.startswith("en") and project.target_language == "en":
                project.target_language = "zh"
        project.recognition_engine = "faster-whisper"
        reference_note = "（参考文稿辅助）" if reference_prompt else ""
        project.subtitle_source = f"本地 Whisper {model_name} 转写{reference_note}"
        project.status = ProjectStatus.REVIEW
        return project

    def translate_missing(
        self, project: Project, progress: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> Project:
        ensure_not_cancelled(cancel_requested)
        missing = [caption for caption in project.captions if not caption.translated_text.strip()]
        if not missing:
            return project
        source_language = project.source_language if project.source_language != "auto" else "en"
        target_language = project.target_language
        if target_language == source_language or (target_language == "zh" and source_language.startswith("zh")):
            target_language = "en"
        translator = self.translator
        if translator is None:
            argos = ArgosTranslator(
                self.runner.root, source_language, target_language,
                data_root=self.runner.data_root,
            )
            if argos.available():
                translator = argos
                project.translation_engine = "Argos Translate 1.11.0"
        if translator is None and self.runner.status().available:
            translator = PyVideoTransTranslator(self.runner, source_language, target_language)
            project.translation_engine = "pyVideoTrans-local"
        if translator is None:
            translator = LocalTranslator()
        batch_size = 40
        translated_count = 0
        for start in range(0, len(missing), batch_size):
            ensure_not_cancelled(cancel_requested)
            batch = missing[start:start + batch_size]
            translations = translator.translate([caption.source_text for caption in batch])
            if len(translations) != len(batch):
                raise RuntimeError("翻译提供方返回的字幕数量不匹配")
            for caption, translation in zip(batch, translations):
                caption.translated_text = translation.strip()
            translated_count += len(batch)
            ensure_not_cancelled(cancel_requested)
            if progress:
                percent = 85.0 + translated_count / len(missing) * 14.0
                progress(percent, f"正在翻译 {translated_count}/{len(missing)} 条字幕")
        if progress:
            progress(100.0, "转写和翻译已完成")
        return project

    def export_package(
        self, project: Project, destination: str | Path, create_zip: bool = False,
        progress: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> Path:
        ensure_not_cancelled(cancel_requested)
        if not project.captions:
            raise ValueError("没有可导出的字幕")
        if not project.media_path:
            raise ValueError("没有可导出的本地媒体")
        destination = Path(destination)
        safe_title = "".join(character if character not in '\\/:*?\"<>|' else "_" for character in project.title).strip() or "daily_english"
        package = destination / safe_title
        package.mkdir(parents=True, exist_ok=True)
        mp3_path = package / f"{safe_title}.mp3"
        if progress:
            progress(5.0, "正在检查字幕并准备导出…")
            progress(10.0, "正在从媒体提取 MP3…")
        self._to_mp3(Path(project.media_path), mp3_path)
        ensure_not_cancelled(cancel_requested)
        if progress:
            progress(72.0, "正在生成双语字幕和元数据…")
        srt_path = package / f"{safe_title}_中英双语.srt"
        write_srt(
            project.captions, srt_path, require_bilingual=True,
            source_first=project.subtitle_order != "translated_first",
        )
        (package / "source.url.txt").write_text(project.source_url or "本地导入，无线上来源链接。", encoding="utf-8")
        metadata = {
            "title": project.title, "author": project.author, "provider": project.provider,
            "source_url": project.source_url, "media_path": project.media_path,
            "reference_path": project.reference_path,
            "subtitle_source": project.subtitle_source, "status": ProjectStatus.EXPORTED.value,
            "source_language": project.source_language, "target_language": project.target_language,
            "subtitle_order": project.subtitle_order, "recognition_engine": project.recognition_engine,
            "translation_engine": project.translation_engine, "alignment_enabled": project.alignment_enabled,
            "download_status": project.download_status.value, "download_format": project.download_format,
        }
        (package / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        ensure_not_cancelled(cancel_requested)
        if create_zip:
            if progress:
                progress(88.0, "正在压缩 ZIP 素材包…")
            zip_path = destination / f"{safe_title}.zip"
            with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
                for file_path in package.iterdir():
                    ensure_not_cancelled(cancel_requested)
                    archive.write(file_path, file_path.name)
        project.status = ProjectStatus.EXPORTED
        if progress:
            progress(100.0, "导出完成")
        return package

    @staticmethod
    def _to_mp3(source: Path, destination: Path) -> None:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        command = [ffmpeg, "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-q:a", "3", str(destination)]
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_subprocess_kwargs(),
        )
        if result.returncode:
            raise RuntimeError(f"无法提取 MP3：{result.stderr[-800:]}")
