# Windows 编译与打包

## 环境要求

- Windows 10 或 Windows 11（64 位）
- Git for Windows
- Python 3.11、3.12 或 3.13，推荐 3.13
- Python 3.10（构建内置 Argos 离线翻译运行时）
- PowerShell 5.1 或 PowerShell 7
- Inno Setup 6（仅构建单文件安装程序时需要）
- 可访问 PyPI；安装可选引擎时还需访问 GitHub 与模型仓库

Python 安装时请启用 `py launcher`。项目虚拟环境、依赖缓存和临时文件都创建在仓库目录内。

## 一键构建

```powershell
git clone https://github.com/ZUKUNFTL/daily-english-resource-assistant.git
cd daily-english-resource-assistant
powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1 -BuildExe
```

构建产物：

```text
dist\每日英语听力资源助手\每日英语听力资源助手.exe
```

构建的是 onedir 应用，运行时必须保留整个 `每日英语听力资源助手` 文件夹，不能只复制其中的 EXE。

## 构建单文件安装程序

安装程序面向普通用户分发，目标电脑不需要 Git 或 Python。它包含桌面程序、独立 Argos 运行时、英译中和中译英模型，以及 Whisper `small`、`medium` 模型；`large-v3` 仍按需下载并缓存在用户目录。

首次准备构建环境：

```powershell
.\setup_windows.ps1 -PythonVersion 3.13
.\engine\setup_argos.ps1
winget install --id JRSoftware.InnoSetup -e --source winget
```

完整构建：

```powershell
.\build_installer.ps1
```

产物：

```text
installer-output\DailyEnglishResourceAssistant-Setup-<版本>.exe
```

`build_installer.ps1` 会依次构建主程序、精简的 Argos Python 3.10 独立运行时、检查或下载 Whisper `small` 和 `medium` 模型，再调用 Inno Setup 编译安装包。若两个程序中间产物已经存在，可用：

```powershell
.\build_installer.ps1 -SkipApplicationBuild -SkipArgosBuild
```

版本默认读取 `pyproject.toml`，也可用 `-Version 0.1.2` 指定。Inno Setup 的命令行编译器会从常见的当前用户或系统安装目录自动查找；找不到时脚本会给出安装命令。

安装版默认写入：

```text
程序：%LOCALAPPDATA%\Programs\DailyEnglishResourceAssistant
数据：%LOCALAPPDATA%\DailyEnglishResourceAssistant
```

它按当前用户安装，不要求管理员权限。卸载器删除程序与安装包部署的 Argos 文件，但保留运行后产生的资料库、设置、Whisper 缓存和导出成果。

## 分步构建

```powershell
.\setup_windows.ps1
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
.\build_windows.ps1
```

如果旧版 EXE 正在运行，Windows 会锁定发布目录。请先关闭应用，或将新版输出到另一个目录：

```powershell
.\build_windows.ps1 -DistPath dist_latest
```

## 可选本地引擎

源码版的完整中英双语能力需要 Argos Translate；pyVideoTrans sidecar 可选：

```powershell
.\engine\setup_sidecar.ps1
.\engine\setup_argos.ps1
```

sidecar 固定到 `engine/pyvideotrans.lock.json` 中记录的 pyVideoTrans commit，并自动应用 `engine/patches/pyvideotrans-progress.patch`。模型按需下载，不包含在 Git 仓库或 EXE 中。

## GitHub Actions

每次推送到 `main` 都会运行单元测试并生成 Windows 构建产物。进入仓库的 Actions 页面，打开成功的 `Windows build`，即可下载 artifact。
