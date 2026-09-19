# 每日英语听力资源助手

一个面向 Windows 的本地英语学习素材整理工具。它可以发现或导入公开视频与音频，生成中英双语字幕，并导出适合“每日英语听力”等学习场景使用的 `MP3 + SRT + metadata + ZIP` 素材包。

## 功能

- 搜索 TED、YouTube 和 B 站学习资源，或直接粘贴 YouTube、B 站、视频号链接。
- 使用 yt-dlp 下载用户明确选择且无需登录的 YouTube/B 站公开音频或视频。
- 导入本地 MP4、MP3、WAV、SRT、TXT、DOCX 和可提取文字的 PDF。
- 中文音频生成“中文原文 + 英文译文”，英语音频生成“英文原文 + 中文译文”。
- 本地 pyVideoTrans / faster-whisper 转写，Argos Translate 离线翻译。
- 模型下载、模型加载、转写和翻译进度显示。
- 模型管理页可查看缓存状态和占用，并支持预下载、删除及打开缓存目录。
- 多任务队列：下载任务并行，字幕任务支持 1 或 2 个并发任务。
- 任务可取消；异常退出后会把中断项目恢复为可重试状态。
- TXT、DOCX、可提取文字的 PDF 可作为 Whisper 参考文稿辅助识别。
- SQLite 本地资料库、字幕编辑、历史项目重开和 ZIP 导出。

## 普通用户：直接安装

发布版提供一个可直接运行的 Windows 安装程序：

```text
DailyEnglishResourceAssistant-Setup-0.1.1.exe
```

双击后按向导安装即可。安装程序会安装主程序、开始菜单和可选桌面快捷方式，并自带中英 Argos 离线翻译运行时与模型；目标电脑不需要安装 Git、Python 或开发依赖。默认安装到当前用户的：

```text
%LOCALAPPDATA%\Programs\DailyEnglishResourceAssistant
```

安装包已经内置默认的 Whisper `small` 模型，新电脑无需连接模型站点即可直接转写。`medium` 和 `large-v3` 体积较大，仍会在第一次使用时下载，之后从本机缓存加载。安装程序当前未做商业代码签名，Windows SmartScreen 可能显示“未知发布者”；请从可信的项目发布页获取，并在需要时核对发布页提供的 SHA-256。

可在 Windows“设置 → 应用 → 已安装的应用”中卸载。为避免误删用户成果，卸载程序会保留资料库、设置、已下载的 Whisper 模型和导出文件。

## 开发者：从 Clone 到可运行程序

如果已经安装 Git、Python 3.13、Python 3.10 和 Windows Python Launcher，可以直接依次执行：

```powershell
git clone https://github.com/ZUKUNFTL/daily-english-resource-assistant.git
cd daily-english-resource-assistant
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -PythonVersion 3.13
powershell -NoProfile -ExecutionPolicy Bypass -File .\engine\setup_argos.ps1
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
& ".\dist\每日英语听力资源助手\每日英语听力资源助手.exe"
```

下面是每一步的说明和可选配置。

### 1. 开发环境要求

- Windows 10/11 64 位。
- Git for Windows。
- Python 3.11、3.12 或 3.13；推荐 Python 3.13，并安装 Windows Python Launcher（`py.exe`）。
- 如果需要中英双语翻译，还要安装 Python 3.10，供隔离的 Argos/pyVideoTrans 环境使用。
- 首次安装依赖、Argos 翻译包或 Whisper 模型时需要联网。
- 建议至少预留 8 GB 磁盘空间；使用 `large-v3` 建议 16 GB 或更多内存。

先在 PowerShell 中确认 Python Launcher 和已安装版本：

```powershell
py --version
py -0p
```

### 2. 克隆项目

```powershell
git clone https://github.com/ZUKUNFTL/daily-english-resource-assistant.git
cd daily-english-resource-assistant
```

后续命令都应在项目根目录执行。项目路径可以包含中文，但建议不要放在需要管理员权限的目录中。

### 3. 安装主程序依赖

推荐使用 Python 3.13：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -PythonVersion 3.13
```

脚本会在项目内创建 `.venv`，安装程序依赖、PyInstaller 和 pytest。也可以指定 `3.11` 或 `3.12`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -PythonVersion 3.12
```

### 4. 安装离线中英翻译（推荐）

只安装主程序即可进行 Whisper 语音识别；要自动生成另一种语言的字幕，还需要 Argos Translate。确认 `py -3.10` 可用后运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\engine\setup_argos.ps1
```

该脚本会创建独立的 Python 3.10 环境，并下载英译中、汉译英模型。Argos 安装完成后不需要每次联网。

pyVideoTrans sidecar 是可选项，普通使用不需要安装。需要其扩展处理能力时再执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\engine\setup_sidecar.ps1
```

sidecar 固定到 [版本锁定文件](engine/pyvideotrans.lock.json) 中记录的 commit，并与主程序 Python 环境隔离。未安装 sidecar 时，程序使用内置的 `faster-whisper + Argos Translate` 流程。

### 5. 从源码启动

```powershell
.\start_app.cmd
```

也可以直接使用 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_app.ps1
```

### 6. 运行测试

构建前建议先运行不会联网的自动化测试：

```powershell
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
```

### 7. 编译 Windows EXE

已有 `.venv` 时执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

也可以首次安装依赖并直接构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -PythonVersion 3.13 -BuildExe
```

构建结果位于：

```text
dist\每日英语听力资源助手\每日英语听力资源助手.exe
```

这是 PyInstaller `onedir` 构建，不是 MSI 安装包。运行、复制或发布时必须保留整个 `dist\每日英语听力资源助手` 文件夹，不能只复制其中的 EXE。

### 8. 构建一键安装程序

先完成前面的主程序和 Argos 安装，再安装 [Inno Setup](https://jrsoftware.org/isdl.php)：

```powershell
winget install --id JRSoftware.InnoSetup -e --source winget
```

然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_installer.ps1
```

脚本会重新构建桌面程序、生成独立 Argos 运行时，并把中英翻译模型及默认 Whisper `small` 模型合并为单文件安装程序。构建机尚未缓存 `small` 时，脚本会先自动下载：

```text
installer-output\DailyEnglishResourceAssistant-Setup-0.1.1.exe
```

如果主程序和 Argos 独立运行时已经构建完成，可以跳过对应步骤以缩短重复打包时间：

```powershell
.\build_installer.ps1 -SkipApplicationBuild -SkipArgosBuild
```

版本默认读取 `pyproject.toml`；发布时也可显式指定四段以内的数字版本：

```powershell
.\build_installer.ps1 -Version 0.1.1
```

### 9. 运行编译后的程序

```powershell
& ".\dist\每日英语听力资源助手\每日英语听力资源助手.exe"
```

如果 Windows SmartScreen 提示未知发布者，这是因为本地构建没有代码签名。请只运行自己从可信源码构建的文件。

### 10. 创建桌面快捷方式（可选）

在项目根目录运行：

```powershell
$projectRoot = (Resolve-Path ".").Path
$exe = Join-Path $projectRoot "dist\每日英语听力资源助手\每日英语听力资源助手.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop "每日英语听力资源助手.lnk"))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path -Parent $exe
$shortcut.Description = "每日英语听力资源助手"
$shortcut.Save()
```

## 模型、缓存与本地数据

- 普通 onedir EXE 不包含 Whisper 模型；一键安装程序内置默认 `small`。`medium` 和 `large-v3` 只在首次使用或在“模型管理”页主动下载时联网，之后直接读取本地缓存。
- 源码版和仓库内 `dist` 的默认模型缓存：`work\cache\huggingface\hub`。
- 安装版的默认模型缓存：`%LOCALAPPDATA%\DailyEnglishResourceAssistant\work\cache\huggingface\hub`。
- 当前三个模型大约占用：`small` 464 MB、`medium` 1.43 GB、`large-v3` 2.88 GB。
- Argos 翻译模型：`work\models\argos`。
- 源码版设置和资料库：`data\settings.json`、`data\library.sqlite3`；安装版位于 `%LOCALAPPDATA%\DailyEnglishResourceAssistant\data`。
- 输出、缓存、模型和本地数据库都不进入 Git。重新构建 EXE 不会删除这些数据。

编译后的程序放在当前仓库的 `dist` 中运行时，会与源码版共用上述模型和数据。如果把 `dist` 文件夹单独复制到另一台电脑，Whisper 可以重新下载模型，但 Argos 翻译环境不会自动随该 onedir 目录复制；面向普通用户分发时请使用 `build_installer.ps1` 生成的安装程序，它已经包含独立 Argos 运行时、中英模型和默认 Whisper `small` 模型。

## 更新与重新构建

关闭正在运行的程序，然后执行：

```powershell
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -PythonVersion 3.13
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

构建路径不变时，原桌面快捷方式不需要重建。模型缓存、资料库和输出不会被 `git pull` 或正常构建删除。

## 常见问题

### 提示“未找到 Windows Python Launcher”

重新安装 python.org 的 Windows 版 Python，并启用 Python Launcher。然后确认 `py -0p` 能列出所需版本。

### 没有生成中文字幕或英文翻译

安装版已经自带离线翻译。如果是从源码或仓库内 `dist` 运行，请执行 `engine\setup_argos.ps1`。Whisper 模型只负责语音识别，不负责中英翻译。

### 第一次转写耗时较长

安装版的 `small` 已经内置，无需首次下载。`medium` 或 `large-v3` 第一次使用时需要下载；程序会使用较长超时并自动重试，成功后显示“正在从本地缓存加载”，不会重复下载。大模型从磁盘加载本身仍需要一些时间。

### 构建时提示目录被占用

先关闭所有“每日英语听力资源助手”窗口，再重新执行 `build_windows.ps1`。也可以临时输出到其他目录：

```powershell
.\build_windows.ps1 -DistPath dist_latest
```

### EXE 能打开但处理时提示缺少 ONNX 文件

不要复制单个 EXE；保留完整的 onedir 文件夹，并使用当前版本的 `build_windows.ps1` 重新构建。构建脚本会检查 `silero_vad_v6.onnx` 是否进入产物。

### 如何彻底卸载

安装版可在 Windows“设置 → 应用 → 已安装的应用”中正常卸载。卸载后如果确认不再需要任何资料库、设置和模型缓存，可手动删除 `%LOCALAPPDATA%\DailyEnglishResourceAssistant`；请先备份需要的文件。

源码版没有注册安装信息，先备份需要的 `data` 和 `outputs`，再删除项目目录和手动创建的桌面快捷方式即可。

更详细的构建说明见 [Windows 编译文档](docs/BUILD_WINDOWS.md)。GitHub Actions 也会自动测试并生成 Windows artifact。

## 使用流程

1. 在“资源搜索”搜索标题或粘贴平台链接，也可以直接导入本地媒体。
2. 选择源语言、目标语言和 `small`、`medium` 或 `large-v3` 模型。
3. 建立项目并点击“加入处理队列”。
4. 在“任务中心”查看模型下载、转写和翻译进度。
5. 在“字幕预览”修订文本与时间码，然后后台导出素材包；可选择导出后自动打开目录。

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

## 在线回归测试（开发者可选）

普通离线测试已包含在前面的安装步骤中。需要显式运行 YouTube/B 站在线回归时：

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
installer/               Inno Setup 安装程序定义
tests/                   单元测试和显式在线回归脚本
docs/                    构建与使用文档
licenses/                第三方许可证副本
.github/workflows/       Windows 自动测试和构建
```

## 许可证

本项目按 [GNU GPL-3.0](LICENSE) 发布。第三方组件、版本和许可证见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。安全问题请按 [SECURITY.md](SECURITY.md) 说明报告。
