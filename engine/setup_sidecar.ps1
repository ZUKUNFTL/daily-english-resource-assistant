param(
    [string]$Python310 = "py"
)

$ErrorActionPreference = "Stop"
$engineRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $engineRoot
$cache = Join-Path $projectRoot "work\cache\pip"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$env:PIP_CACHE_DIR = $cache
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$venv = Join-Path $engineRoot "pyvideotrans\.venv"
$clone = Join-Path $engineRoot "pyvideotrans\source"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "未找到 Git，请先安装 Git for Windows。"
}

if ($Python310 -eq "py") {
    & py -3.10 -m venv $venv
} else {
    & $Python310 -m venv $venv
}
if ($LASTEXITCODE -ne 0) { throw "无法创建 Python 3.10 sidecar 环境。" }
& (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
if (-not (Test-Path $clone)) {
    git clone --filter=blob:none --no-checkout https://github.com/jianchang512/pyvideotrans.git $clone
}
Push-Location $clone
if (Test-Path (Join-Path $clone ".git")) {
    git checkout --detach 36d40dd5fc31671b89cfa7ea0f4fa6625d27efbc
} else {
    Write-Host "Using pre-extracted fixed commit source archive."
}
$progressPatch = Join-Path $engineRoot "patches\pyvideotrans-progress.patch"
$progressSource = Join-Path $clone "videotrans\process\stt_faster.py"
if (-not (Select-String -LiteralPath $progressSource -SimpleMatch "[STT_PROGRESS]" -Quiet)) {
    git apply --whitespace=nowarn $progressPatch
    if ($LASTEXITCODE -ne 0) { throw "无法应用 pyVideoTrans 进度补丁。" }
}
& (Join-Path $venv "Scripts\python.exe") -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "pyVideoTrans 依赖安装失败。" }
Pop-Location
Write-Host "pyVideoTrans sidecar installed."
