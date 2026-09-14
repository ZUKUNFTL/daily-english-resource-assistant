# 每日英语听力资源助手

一个面向 Windows 的本地英语学习素材整理工具。它可以发现或导入公开视频与音频，生成中英双语字幕，并导出适合“每日英语听力”等学习场景使用的 `MP3 + SRT + metadata + ZIP` 素材包。

## 功能

- 搜索 TED、YouTube 和 B 站学习资源，或直接粘贴 YouTube、B 站、视频号链接。
- 使用 yt-dlp 下载用户明确选择且无需登录的 YouTube/B 站公开音频或视频。
- 导入本地 MP4、MP3、WAV、SRT、TXT、DOCX 和可提取文字的 PDF。
- 中文音频生成“中文原文 + 英文译文”，英语音频生成“英文原文 + 中文译文”。
- 本地 pyVideoTrans / faster-whisper 转写，Argos Translate 离线翻译。
- 模型下载、模型加载、转写和翻译进度显示。
- 多任务队列：下载任务并行，字幕任务支持 1 或 2 个并发任务。
- SQLite 本地资料库、字幕编辑、历史项目重开和 ZIP 导出。

## 快速开始

### 从源码运行

要求 Windows 10/11、Git 和 Python 3.11–3.13，推荐 Python 3.13。

```powershell
git clone https://github.com/ZUKUNFTL/daily-english-resource-assistant.git
cd daily-english-resource-assistant
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
.\start_app.cmd
```

### 编译 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -BuildExe
```

输出位置：

```text
dist\每日英语听力资源助手\每日英语听力资源助手.exe
```

这是 onedir 构建，发布或复制时要保留整个 `每日英语听力资源助手` 文件夹。更完整的说明见 [Windows 编译文档](docs/BUILD_WINDOWS.md)。GitHub Actions 也会自动测试并生成可下载的 Windows artifact。

## 安装本地双语引擎

主程序使用 Python 3.11–3.13；固定版本的 pyVideoTrans sidecar 单独使用 Python 3.10，从而隔离 PyTorch、CUDA 和 Python 版本冲突。

```powershell
.\engine\setup_sidecar.ps1
.\engine\setup_argos.ps1
```

pyVideoTrans 固定到 [版本锁定文件](engine/pyvideotrans.lock.json) 中记录的 commit，并在安装时应用实时转写进度补丁。Whisper 模型与 Argos 模型按需下载，不进入 Git 仓库，也不会打包进 EXE。

sidecar 未安装时，英语和中文识别可回退到 `faster-whisper`。翻译模型不可用时，程序会保留原文并明确提示，不会生成空白或伪造译文。

## 使用流程

1. 在“资源搜索”搜索标题或粘贴平台链接，也可以直接导入本地媒体。
2. 选择源语言、目标语言和 `small`、`medium` 或 `large-v3` 模型。
3. 建立项目并点击“加入处理队列”。
4. 在“任务中心”查看模型下载、转写和翻译进度。
5. 在“字幕预览”修订文本与时间码，然后导出素材包。

详细操作见 [使用说明](docs/USER_GUIDE.md)。

## 导出结构

```text
标题/
├── 标题.mp3
├── 标题_中英双语.srt
├── source.url.txt
└── metadata.json
标题.zip
```

## 测试

普通单元测试不会联网：

```powershell
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
```

显式运行 YouTube/B 站在线回归：

```powershell
$env:PYTHONPATH = "app"
$env:ONLINE_REGRESSION = "1"
.\.venv\Scripts\python.exe tests\run_online_regression.py
```

测试媒体与结果保存在本地 `resources` 目录，不提交到仓库。网络不可用或平台临时限制时，在线脚本会明确报告 `SKIPPED`。

## 数据与隐私

- API Key、资料库、设置、媒体、模型、缓存和临时文件只保存在本地，并已由 `.gitignore` 排除。
- YouTube Data API Key 只用于搜索和元数据，不等于下载授权。
- 程序不接收账号密码，不读取浏览器 Cookie，不安装抓包证书，也不绕过 DRM、登录、会员或地区限制。
- 视频号只在微信匿名官方响应直接返回媒体流时下载；否则需要通过官方功能保存，或取得作者提供的原文件。

请只处理自己拥有、明确获准使用或许可允许下载的内容。

## 项目结构

```text
app/daily_english/       PySide6 应用与核心流程
engine/                  sidecar、离线翻译安装脚本与补丁
tests/                   单元测试和显式在线回归脚本
docs/                    构建与使用文档
licenses/                第三方许可证副本
.github/workflows/       Windows 自动测试和构建
```

## 许可证

本项目按 [GNU GPL-3.0](LICENSE) 发布。第三方组件、版本和许可证见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。安全问题请按 [SECURITY.md](SECURITY.md) 说明报告。
