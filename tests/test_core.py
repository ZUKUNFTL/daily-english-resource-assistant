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
from daily_english.pipeline import CaptionPipeline, LocalTranslator
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
