# Windows 编译与打包

## 环境要求

- Windows 10 或 Windows 11（64 位）
- Git for Windows
- Python 3.11、3.12 或 3.13，推荐 3.13
- PowerShell 5.1 或 PowerShell 7
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

完整中英双语能力建议安装 Python 3.10 sidecar 和 Argos Translate：

```powershell
.\engine\setup_sidecar.ps1
.\engine\setup_argos.ps1
```

sidecar 固定到 `engine/pyvideotrans.lock.json` 中记录的 pyVideoTrans commit，并自动应用 `engine/patches/pyvideotrans-progress.patch`。模型按需下载，不包含在 Git 仓库或 EXE 中。

## GitHub Actions

每次推送到 `main` 都会运行单元测试并生成 Windows 构建产物。进入仓库的 Actions 页面，打开成功的 `Windows build`，即可下载 artifact。
