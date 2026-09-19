param(
    [string]$Version = "",
    [switch]$SkipApplicationBuild,
    [switch]$SkipArgosBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$applicationBuild = Join-Path $projectRoot "dist\每日英语听力资源助手\每日英语听力资源助手.exe"
$argosBuild = Join-Path $projectRoot "build\installer-runtime\argos_translate\argos_translate.exe"
$argosModels = Join-Path $projectRoot "work\models\argos"
$argosData = Join-Path $projectRoot "work\data\argos-translate"
$whisperHubCache = Join-Path $projectRoot "work\cache\huggingface\hub"
$whisperSmallCache = Join-Path $whisperHubCache "models--Systran--faster-whisper-small"
$installerScript = Join-Path $projectRoot "installer\daily_english_assistant.iss"

function Test-WhisperSmallCache {
    param([string]$RepositoryPath)
    $mainReference = Join-Path $RepositoryPath "refs\main"
    if (-not (Test-Path -LiteralPath $mainReference -PathType Leaf)) { return $false }
    $revision = (Get-Content -LiteralPath $mainReference -Raw).Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { return $false }
    $snapshot = Join-Path $RepositoryPath "snapshots\$revision"
    foreach ($file in @("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")) {
        if (-not (Test-Path -LiteralPath (Join-Path $snapshot $file) -PathType Leaf)) { return $false }
    }
    return (Get-Item -LiteralPath (Join-Path $snapshot "model.bin")).Length -gt 100MB
}

if (-not $Version) {
    $projectFile = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
    $match = [regex]::Match($projectFile, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw "无法从 pyproject.toml 读取版本号。" }
    $Version = $match.Groups[1].Value
}
if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') {
    throw "安装包版本号必须是数字版本，例如 0.1.0：$Version"
}

if (-not $SkipApplicationBuild) {
    & (Join-Path $projectRoot "build_windows.ps1")
    if ($LASTEXITCODE -ne 0) { throw "桌面程序构建失败。" }
}
if (-not (Test-Path -LiteralPath $applicationBuild -PathType Leaf)) {
    throw "缺少桌面程序构建产物：$applicationBuild"
}

if (-not $SkipArgosBuild) {
    & (Join-Path $projectRoot "build_argos_runtime.ps1") -InstallDependencies
    if ($LASTEXITCODE -ne 0) { throw "Argos 独立运行时构建失败。" }
}
if (-not (Test-Path -LiteralPath $argosBuild -PathType Leaf)) {
    throw "缺少 Argos 独立运行时：$argosBuild"
}
if (-not (Test-Path -LiteralPath $argosModels -PathType Container) -or -not (Get-ChildItem -LiteralPath $argosModels -Directory)) {
    throw "缺少 Argos 中英模型。请先运行 engine/setup_argos.ps1。"
}
if (-not (Test-Path -LiteralPath $argosData -PathType Container)) {
    throw "缺少 Argos 运行数据。请先运行一次 engine/setup_argos.ps1。"
}

if (-not (Test-WhisperSmallCache $whisperSmallCache)) {
    $applicationPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $applicationPython -PathType Leaf)) {
        throw "缺少主程序 Python 环境，无法准备内置 small 模型。请先运行 setup_windows.ps1。"
    }
    Write-Host "Downloading the bundled faster-whisper small model..."
    $env:DAILY_ENGLISH_WHISPER_CACHE = $whisperHubCache
    & $applicationPython -c "import os; from faster_whisper.utils import download_model; print(download_model('small', cache_dir=os.environ['DAILY_ENGLISH_WHISPER_CACHE']))"
    if ($LASTEXITCODE -ne 0) { throw "内置 small 模型下载失败。" }
}
if (-not (Test-WhisperSmallCache $whisperSmallCache)) {
    throw "small 模型缓存不完整，无法构建可离线使用的安装包：$whisperSmallCache"
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $iscc) {
    throw "未找到 Inno Setup。请运行：winget install --id JRSoftware.InnoSetup -e --source winget"
}

$outputDirectory = Join-Path $projectRoot "installer-output"
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
& $iscc "/DProjectRoot=$projectRoot" "/DAppVersion=$Version" $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "安装程序编译失败，退出码：$LASTEXITCODE"
}

$installer = Join-Path $outputDirectory "DailyEnglishResourceAssistant-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "安装程序未生成：$installer"
}
$installerItem = Get-Item -LiteralPath $installer
$installerHash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
Write-Host "Installer built: $installer"
Write-Host ("Size: {0:N2} MB" -f ($installerItem.Length / 1MB))
Write-Host "SHA256: $($installerHash.Hash)"
