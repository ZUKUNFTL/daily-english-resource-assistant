from __future__ import annotations

import re
from pathlib import Path

from .models import Caption

TIME_PATTERN = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def seconds(parts: tuple[str, str, str, str]) -> float:
    hours, minutes, whole_seconds, milliseconds = map(int, parts)
    return hours * 3600 + minutes * 60 + whole_seconds + milliseconds / 1000


def read_srt(path: str | Path, bilingual: bool = True) -> list[Caption]:
    content = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    captions: list[Caption] = []
    for expected, block in enumerate(content.split("\n\n"), 1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0].strip() != str(expected):
            raise ValueError(f"第 {expected} 条字幕格式错误")
        match = TIME_PATTERN.match(lines[1].strip())
        if not match:
            raise ValueError(f"第 {expected} 条字幕时间码错误")
        start = seconds(match.groups()[:4])
        end = seconds(match.groups()[4:])
        text = [line.strip() for line in lines[2:] if line.strip()]
        if not text:
            raise ValueError(f"第 {expected} 条字幕内容为空")
        if bilingual:
            captions.append(Caption(start, end, text[0], " ".join(text[1:])))
        else:
            captions.append(Caption(start, end, " ".join(text)))
    validate(captions)
    return captions


def validate(captions: list[Caption], require_bilingual: bool = False) -> None:
    previous_end = -1.0
    for index, caption in enumerate(captions, 1):
        if caption.start >= caption.end:
            raise ValueError(f"第 {index} 条字幕结束时间必须晚于开始时间")
        if caption.start < previous_end:
            raise ValueError(f"第 {index} 条字幕与上一条重叠")
        if not caption.source_text.strip():
            raise ValueError(f"第 {index} 条字幕缺少原文")
        if require_bilingual and not caption.translated_text.strip():
            raise ValueError(f"第 {index} 条字幕缺少译文")
        previous_end = caption.end


def write_srt(
    captions: list[Caption], path: str | Path, require_bilingual: bool = True,
    source_first: bool = True,
) -> None:
    validate(captions, require_bilingual=require_bilingual)
    blocks = []
    for index, caption in enumerate(captions, 1):
        source_text = " ".join(caption.source_text.split())
        translated_text = " ".join(caption.translated_text.split())
        text_lines = [source_text, translated_text]
        if not source_first:
            text_lines.reverse()
        lines = [str(index), f"{timestamp(caption.start)} --> {timestamp(caption.end)}"] + [line for line in text_lines if line]
        blocks.append("\n".join(lines))
    Path(path).write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig", newline="\n")
