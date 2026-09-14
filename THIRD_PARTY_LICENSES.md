# Third-party components

本项目通过 sidecar 调用以下开源组件：

- pyVideoTrans 4.12, GPL-3.0: https://github.com/jianchang512/pyvideotrans
- faster-whisper, MIT: https://github.com/SYSTRAN/faster-whisper
- WhisperX, BSD-2-Clause: https://github.com/m-bain/whisperX
- Argos Translate, MIT/CC0: https://github.com/argosopentech/argos-translate
- yt-dlp 2026.8.19, Unlicense: https://github.com/yt-dlp/yt-dlp
- media-parser 视频号匿名解析思路, MIT, commit `53b57a54d633dba3147b1ef4900da47ce6be31fe`: https://github.com/ucmao/media-parser
  - 许可证副本：`licenses/media-parser-LICENSE.txt`

`engine/pyvideotrans.lock.json` 记录 pyVideoTrans 的固定 commit。源码仓库和默认 EXE 不直接包含 pyVideoTrans、Whisper 模型或 Argos 模型；安装脚本按需下载。发布包含 sidecar 的安装包时，应同时提供相应许可证文本、源代码获取方式和本清单。
