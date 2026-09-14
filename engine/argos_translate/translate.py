from __future__ import annotations

import json
import sys

from argostranslate import translate


def normalize_language(code: str) -> str:
    return "zh" if code.lower().startswith("zh") else code.lower().split("-")[0]


def main() -> int:
    request = json.load(sys.stdin)
    source_code = normalize_language(request["source_language"])
    target_code = normalize_language(request["target_language"])
    languages = {language.code: language for language in translate.get_installed_languages()}
    if source_code not in languages or target_code not in languages:
        raise RuntimeError(f"缺少 Argos 离线翻译模型：{source_code}->{target_code}")
    translator = languages[source_code].get_translation(languages[target_code])
    translations = [translator.translate(text) for text in request["texts"]]
    json.dump({"translations": translations}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
