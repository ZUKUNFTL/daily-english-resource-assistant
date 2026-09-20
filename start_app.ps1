$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "主程序环境不存在，请先安装依赖。"
}

$env:PYTHONPATH = Join-Path $projectRoot "app"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "work\cache\pip"
$env:HF_HOME = Join-Path $projectRoot "work\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME "hub"
$env:TORCH_HOME = Join-Path $projectRoot "work\cache\torch"
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP

New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR, $env:HF_HOME, $env:TORCH_HOME, $env:TEMP | Out-Null
Set-Location $projectRoot
& $python -m daily_english
