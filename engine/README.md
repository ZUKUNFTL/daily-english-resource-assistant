# pyVideoTrans sidecar

本项目通过独立 Python 3.10 环境调用 pyVideoTrans CLI，避免与桌面应用的 Python 运行时冲突。

固定来源：`https://github.com/jianchang512/pyvideotrans`

固定版本：`4.12`

固定 commit：`36d40dd5fc31671b89cfa7ea0f4fa6625d27efbc`

许可证：GPL-3.0。发布应用时必须随软件提供 GPL 文本、源代码获取方式及第三方依赖声明。

安装条件：Python 3.10、Git 和网络。Windows 可以运行 `setup_sidecar.ps1` 创建 `.venv`、拉取固定 commit，并应用 `patches/pyvideotrans-progress.patch`；运行时直接从 `engine/pyvideotrans/source/cli.py` 调用。

本机回归环境将核心 STT 依赖（PyTorch、faster-whisper、PySide6、音频处理库）安装在项目目录的独立虚拟环境中。应用默认优先使用 Argos Translate 完成离线中英翻译，不依赖 Google 免费翻译接口；没有可用翻译模型时会保留原文并提示安装，不生成空译文。
