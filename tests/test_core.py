from pathlib import Path
import sys
import types

from daily_english.database import LibraryDatabase
from daily_english.engine import EngineRunner
from daily_english.downloader import (
    DownloadError, WeChatChannelsDownloader, YtDlpDownloader, detect_platform,
    safe_title, validate_download_url,
)
from daily_english.models import Caption, Project, ProjectStatus
from daily_english.model_cache import repository_cache_path
from daily_english.pipeline import CaptionPipeline, LocalTranslator, resolve_faster_whisper_model
from daily_english.processes import TaskCancelled
from daily_english.references import read_reference_text, whisper_reference_prompt
from daily_english import settings as application_settings
from daily_english.subtitles import read_srt, validate, write_srt


def test_srt_round_trip(tmp_path: Path) -> None:
    captions = [
        Caption(0.0, 1.2, "Hello.", "你好。"),
        Caption(1.3, 2.5, "How are you?", "你好吗？"),
    ]
    output = tmp_path / "test.srt"
    write_srt(captions, output)
    assert read_srt(output) == captions


def test_monolingual_srt_wraps_are_not_translations(tmp_path: Path) -> None:
    source = tmp_path / "mono.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nA wrapped source\nsubtitle line\n",
        encoding="utf-8",
    )
    caption = read_srt(source, bilingual=False)[0]
    assert caption.source_text == "A wrapped source subtitle line"
    assert caption.translated_text == ""


def test_export_flattens_internal_newlines(tmp_path: Path) -> None:
    output = tmp_path / "flat.srt"
    write_srt([Caption(0, 1, "English\nsource", "中文\n翻译")], output)
    assert output.read_text(encoding="utf-8-sig").splitlines()[2:] == ["English source", "中文 翻译"]


def test_chinese_source_can_export_source_first(tmp_path: Path) -> None:
    captions = [Caption(0.0, 1.2, "你好。", "Hello.")]
    output = tmp_path / "zh-en.srt"
    write_srt(captions, output, source_first=True)
    lines = output.read_text(encoding="utf-8-sig").splitlines()
    assert lines[2] == "你好。"
    assert lines[3] == "Hello."


def test_srt_rejects_overlapping_timestamps() -> None:
    try:
        validate([Caption(0, 2, "A", "甲"), Caption(1, 3, "B", "乙")])
    except ValueError as error:
        assert "重叠" in str(error)
    else:
        raise AssertionError("Expected timestamp validation to reject overlap")


def test_library_persists_captions(tmp_path: Path) -> None:
    database = LibraryDatabase(tmp_path / "library.sqlite3")
    project = Project(
        None, "Test", source_url="https://example.test", status=ProjectStatus.REVIEW,
        captions=[Caption(0, 1, "English", "中文")],
    )
    saved = database.save_project(project)
    loaded = database.get_project(saved.id)
    assert loaded.title == "Test"
    assert loaded.captions[0].chinese == "中文"


def test_library_persists_language_metadata(tmp_path: Path) -> None:
    database = LibraryDatabase(tmp_path / "language.sqlite3")
    project = Project(
        None, "中文素材", source_language="zh-cn", target_language="en",
        subtitle_order="translated_first", alignment_enabled=True,
        captions=[Caption(0, 1, "你好", "Hello")],
    )
    saved = database.save_project(project)
    loaded = database.get_project(saved.id)
    assert loaded.source_language == "zh-cn"
    assert loaded.target_language == "en"
    assert loaded.subtitle_order == "translated_first"
    assert loaded.alignment_enabled is True


def test_library_recovers_interrupted_projects(tmp_path: Path) -> None:
    database = LibraryDatabase(tmp_path / "recovery.sqlite3")
    project = database.save_project(
        Project(None, "Interrupted", status=ProjectStatus.PROCESSING)
    )

    assert database.recover_interrupted_projects() == 1
    recovered = database.get_project(project.id)
    assert recovered.status == ProjectStatus.FAILED
    assert "重新加入处理队列" in recovered.error
    assert database.recover_interrupted_projects() == 0


class StubTranslator(LocalTranslator):
    def translate(self, texts: list[str]) -> list[str]:
        return [f"translated: {text}" for text in texts]


def test_chinese_project_uses_translation_direction() -> None:
    project = Project(
        None, "中文", source_language="zh-cn", target_language="en",
        captions=[Caption(0, 1, "你好")],
    )
    CaptionPipeline(translator=StubTranslator()).translate_missing(project)
    assert project.captions[0].source_text == "你好"
    assert project.captions[0].translated_text == "translated: 你好"


def test_download_url_platform_validation() -> None:
    assert detect_platform("https://youtu.be/example") == "YouTube"
    assert detect_platform("https://www.bilibili.com/video/BV1xx") == "Bilibili"
    assert detect_platform("https://weixin.qq.com/sph/A1sNLfChlV") == "WeChat Channels"
    assert safe_title('a:b/c*movie') == "a_b_c_movie"
    try:
        validate_download_url("https://example.com/video")
    except DownloadError as error:
        assert "YouTube" in str(error)
    else:
        raise AssertionError("Expected unsupported host to be rejected")


def test_ytdlp_audio_download_uses_safe_options(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            captured.update(options)
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=True):
            assert download is True
            output = tmp_path / "sample.mp3"
            output.write_bytes(b"mp3")
            return {"title": "sample", "uploader": "tester", "duration": 10}

        def prepare_filename(self, info):
            return str(tmp_path / "sample.webm")

    fake_module = types.ModuleType("yt_dlp")
    fake_module.YoutubeDL = FakeYoutubeDL
    fake_utils = types.ModuleType("yt_dlp.utils")
    fake_utils.DownloadError = RuntimeError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", fake_utils)

    result = YtDlpDownloader().download("https://youtu.be/example", tmp_path, "audio")
    assert result.path.name == "sample.mp3"
    assert captured["noplaylist"] is True
    assert "cookiefile" not in captured
    assert captured["format"] == "bestaudio/best"
    assert "ffmpeg_location" in captured


def test_wechat_channels_anonymous_metadata_without_media(tmp_path: Path) -> None:
    class FakeResponse:
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "errCode": 0,
                "data": {
                    "authorInfo": {"nickname": "测试作者"},
                    "feedInfo": {"description": "测试标题\n#英语学习", "coverUrl": "https://finder.video.qq.com/cover"},
                },
            }

    class FakeSession:
        def post(self, *args, **kwargs):
            assert kwargs["json"]["shortUri"] == "A1sNLfChlV"
            return FakeResponse()

    downloader = WeChatChannelsDownloader(FakeSession())
    info = downloader.inspect("https://weixin.qq.com/sph/A1sNLfChlV")
    assert info.title == "测试标题"
    assert info.author == "测试作者"
    assert info.video_url == ""
    try:
        downloader.download("https://weixin.qq.com/sph/A1sNLfChlV", tmp_path)
    except DownloadError as error:
        assert "不读取账号 Cookie" in str(error)
    else:
        raise AssertionError("Expected protected WeChat media to require local import")


def test_engine_parses_model_download_and_stt_progress() -> None:
    percent, message = EngineRunner._progress_from_line("Downloading please wait model.bin 50.00%")
    assert percent == 13.0
    assert "50.0%" in message

    percent, message = EngineRunner._progress_from_line("[STT_PROGRESS] 75.0% Faster-whisper [8]")
    assert percent == 70.0
    assert "75.0%" in message


def test_whisper_model_uses_local_cache_without_network(tmp_path: Path, monkeypatch) -> None:
    calls = []
    messages = []
    snapshot = tmp_path / "snapshot"

    def fake_download(model_name, *, cache_dir, local_files_only):
        calls.append((model_name, Path(cache_dir), local_files_only))
        return str(snapshot)

    monkeypatch.setattr("faster_whisper.utils.download_model", fake_download)
    resolved = resolve_faster_whisper_model(
        "small", tmp_path, lambda _percent, message: messages.append(message),
    )

    assert resolved == snapshot
    assert calls == [("small", tmp_path / "huggingface" / "hub", True)]
    assert messages == ["已找到 small 模型，正在从本地缓存加载…"]


def test_whisper_model_downloads_only_after_cache_miss(tmp_path: Path, monkeypatch) -> None:
    from huggingface_hub.errors import LocalEntryNotFoundError

    calls = []
    messages = []
    snapshot = tmp_path / "downloaded"

    def fake_download(model_name, *, cache_dir, local_files_only):
        calls.append(local_files_only)
        if local_files_only:
            raise LocalEntryNotFoundError("not cached")
        return str(snapshot)

    monkeypatch.setattr("faster_whisper.utils.download_model", fake_download)
    resolved = resolve_faster_whisper_model(
        "medium", tmp_path, lambda _percent, message: messages.append(message),
    )

    assert resolved == snapshot
    assert calls == [True, False]
    assert messages == ["本地没有 medium 模型，正在首次下载…"]


def test_whisper_model_cleans_interrupted_download(tmp_path: Path, monkeypatch) -> None:
    from huggingface_hub.errors import LocalEntryNotFoundError

    incomplete = repository_cache_path("large-v3", tmp_path) / "blobs" / "model.incomplete"
    incomplete.parent.mkdir(parents=True)
    incomplete.write_bytes(b"partial")

    def fake_download(_model_name, *, cache_dir, local_files_only):
        if local_files_only:
            raise LocalEntryNotFoundError("not cached")
        raise OSError("network unavailable")

    monkeypatch.setattr("faster_whisper.utils.download_model", fake_download)
    try:
        resolve_faster_whisper_model("large-v3", tmp_path)
    except RuntimeError as error:
        assert "首次下载失败" in str(error)
    else:
        raise AssertionError("Expected a failed first download")
    assert not incomplete.exists()


def test_reference_text_is_read_and_prompt_is_bounded(tmp_path: Path) -> None:
    reference = tmp_path / "reference.txt"
    reference.write_text("OpenAI terminology.\n" * 300, encoding="utf-8")

    text = read_reference_text(reference)
    prompt = whisper_reference_prompt(text, max_characters=120)
    assert "OpenAI terminology" in prompt
    assert len(prompt) <= 120


def test_reference_text_rejects_empty_document(tmp_path: Path) -> None:
    reference = tmp_path / "empty.txt"
    reference.write_text("   \n", encoding="utf-8")
    try:
        read_reference_text(reference)
    except ValueError as error:
        assert "没有可提取" in str(error)
    else:
        raise AssertionError("Expected an empty reference document to be rejected")


def test_transcribe_passes_reference_text_to_whisper(tmp_path: Path, monkeypatch) -> None:
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"media")
    reference = tmp_path / "reference.txt"
    reference.write_text("The speaker is called Ada Lovelace.", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model_path, **kwargs):
            captured["model_path"] = model_path

        def transcribe(self, media_path, **kwargs):
            captured.update(kwargs)
            return (
                [types.SimpleNamespace(start=0.0, end=1.0, text="Ada Lovelace")],
                types.SimpleNamespace(duration=1.0, language="en"),
            )

    runner = types.SimpleNamespace(
        root=tmp_path,
        data_root=tmp_path,
        cache_root=tmp_path / "work" / "cache",
        temporary_root=tmp_path / "work" / "tmp",
        status=lambda: types.SimpleNamespace(available=False),
    )
    monkeypatch.setattr("faster_whisper.WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(
        "daily_english.pipeline.resolve_faster_whisper_model",
        lambda *args, **kwargs: tmp_path / "cached-model",
    )
    project = Project(
        None, "Reference", media_path=str(media), reference_path=str(reference),
        source_language="en",
    )
    CaptionPipeline(runner=runner).transcribe(project)

    assert captured["initial_prompt"] == "The speaker is called Ada Lovelace."
    assert "参考文稿辅助" in project.subtitle_source


def test_cancelled_pipeline_stops_before_work() -> None:
    project = Project(None, "Cancelled", media_path="missing.mp4")
    try:
        CaptionPipeline().transcribe(project, cancel_requested=lambda: True)
    except TaskCancelled:
        pass
    else:
        raise AssertionError("Expected cancellation before transcription")


def test_file_pickers_remember_purpose_and_shared_directories(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    media_directory = tmp_path / "media"
    export_directory = tmp_path / "exports"
    media_directory.mkdir()
    export_directory.mkdir()
    media_file = media_directory / "sample.mp4"
    media_file.write_bytes(b"video")
    monkeypatch.setattr(application_settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(application_settings, "APP_DIR", tmp_path)

    application_settings.remember_last_path(media_file, "media")
    assert application_settings.last_directory("media") == str(media_directory.resolve())
    assert application_settings.last_directory("subtitle") == str(media_directory.resolve())

    application_settings.remember_last_path(export_directory, "export")
    assert application_settings.last_directory("export") == str(export_directory.resolve())
    assert application_settings.last_directory("media") == str(media_directory.resolve())
    assert application_settings.last_directory("subtitle") == str(export_directory.resolve())


def test_boolean_setting_is_persisted(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(application_settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(application_settings, "APP_DIR", tmp_path)

    assert application_settings.bool_setting("open_export_folder_after_export", True)
    application_settings.set_setting("open_export_folder_after_export", False)
    assert not application_settings.bool_setting("open_export_folder_after_export", True)
