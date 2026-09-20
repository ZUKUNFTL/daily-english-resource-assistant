param(
    [ValidateSet("3.11", "3.12", "3.13")]
    [string]$PythonVersion = "3.13",
    [switch]$BuildExe
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $projectRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "work\cache\pip"
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR, $env:TEMP | Out-Null

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "未找到 Windows Python Launcher。请先安装 Python $PythonVersion，并勾选 py launcher。"
}

if (-not (Test-Path -LiteralPath $python)) {
    & py "-$PythonVersion" -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "无法使用 Python $PythonVersion 创建虚拟环境。"
    }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败。" }
& $python -m pip install -e $projectRoot pyinstaller pytest
if ($LASTEXITCODE -ne 0) { throw "项目依赖安装失败。" }

if ($BuildExe) {
    & (Join-Path $projectRoot "build_windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "EXE 构建失败。" }
}

Write-Host "Main application environment is ready: $python"
