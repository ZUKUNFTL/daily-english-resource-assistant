param(
    [switch]$InstallDependencies,
    [string]$DistPath = "dist"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "work\cache\pip"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot "work\cache\pyinstaller"
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP
$env:PATH = (($env:PATH -split ";" | Where-Object { $_ -and $_ -notlike "*\.cache\codex-runtimes\*" }) -join ";")
New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR, $env:PYINSTALLER_CONFIG_DIR, $env:TEMP | Out-Null

if (-not (Test-Path $python)) {
    throw "未找到主程序虚拟环境：$python。请先运行 setup_windows.ps1。"
}

if ($InstallDependencies) {
    & $python -m pip install -e $projectRoot pyinstaller
}

Set-Location $projectRoot
$resolvedDistPath = if ([System.IO.Path]::IsPathRooted($DistPath)) { $DistPath } else { Join-Path $projectRoot $DistPath }
$applicationName = "每日英语听力资源助手"
& $python -m PyInstaller --noconfirm --clean --windowed --distpath $resolvedDistPath --name $applicationName --paths app --collect-data faster_whisper --add-data "LICENSE;." --add-data "THIRD_PARTY_LICENSES.md;." --add-data "licenses;licenses" app_launcher.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
}

$applicationRoot = Join-Path $resolvedDistPath $applicationName
$executablePath = Join-Path $applicationRoot "$applicationName.exe"
$requiredRuntimeFiles = @(
    (Join-Path $applicationRoot "_internal\faster_whisper\assets\silero_vad_v6.onnx")
)

if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "构建产物缺少主程序：$executablePath"
}

foreach ($runtimeFile in $requiredRuntimeFiles) {
    if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
        throw "构建产物缺少运行资源：$runtimeFile"
    }
}

Write-Host "Build completed: $executablePath"
