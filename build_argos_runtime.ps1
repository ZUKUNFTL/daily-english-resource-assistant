param(
    [switch]$InstallDependencies,
    [string]$DistPath = "build\installer-runtime"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot "engine\argos_translate\.venv\Scripts\python.exe"
$entryPoint = Join-Path $projectRoot "engine\argos_translate\translate.py"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "work\cache\pip"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot "work\cache\pyinstaller-argos"
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP
$env:ARGOS_CHUNK_TYPE = "MINISBD"
New-Item -ItemType Directory -Force -Path $env:PIP_CACHE_DIR, $env:PYINSTALLER_CONFIG_DIR, $env:TEMP | Out-Null

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "未找到 Argos Python 环境。请先运行 engine/setup_argos.ps1。"
}
if ($InstallDependencies) {
    & $python -m pip install "pyinstaller>=6,<7"
    if ($LASTEXITCODE -ne 0) { throw "Argos PyInstaller 安装失败。" }
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Argos 环境中没有 PyInstaller。请添加 -InstallDependencies。"
}

$resolvedDistPath = if ([IO.Path]::IsPathRooted($DistPath)) { $DistPath } else { Join-Path $projectRoot $DistPath }
$workPath = Join-Path $projectRoot "build\argos-runtime"
$specPath = Join-Path $projectRoot "work\tmp\argos-runtime-spec"
New-Item -ItemType Directory -Force -Path $resolvedDistPath, $workPath, $specPath | Out-Null

& $python -m PyInstaller --noconfirm --clean --console --onedir `
    --name "argos_translate" --distpath $resolvedDistPath --workpath $workPath --specpath $specPath `
    --exclude-module stanza --exclude-module torch --exclude-module spacy `
    --exclude-module sympy --exclude-module networkx --exclude-module torchvision `
    --collect-data argostranslate --collect-data minisbd $entryPoint
if ($LASTEXITCODE -ne 0) {
    throw "Argos 独立运行时构建失败，退出码：$LASTEXITCODE"
}

$executable = Join-Path $resolvedDistPath "argos_translate\argos_translate.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Argos 构建产物缺少可执行文件：$executable"
}
Write-Host "Argos runtime built: $executable"
