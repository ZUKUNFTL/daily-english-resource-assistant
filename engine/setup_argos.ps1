param(
    [string]$Python310 = "py -3.10"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$engineRoot = Join-Path $projectRoot "engine\argos_translate"
$venvRoot = Join-Path $engineRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "work\cache\pip"
$env:TEMP = Join-Path $projectRoot "work\tmp"
$env:TMP = $env:TEMP
$env:XDG_DATA_HOME = Join-Path $projectRoot "work\data"
$env:XDG_CONFIG_HOME = Join-Path $projectRoot "work\config"
$env:XDG_CACHE_HOME = Join-Path $projectRoot "work\cache"
$env:ARGOS_PACKAGES_DIR = Join-Path $projectRoot "work\models\argos"
$env:ARGOS_DEVICE_TYPE = "cpu"
$env:ARGOS_CHUNK_TYPE = "MINISBD"
New-Item -ItemType Directory -Force -Path $engineRoot, $env:PIP_CACHE_DIR, $env:TEMP, $env:ARGOS_PACKAGES_DIR | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    if ($Python310 -eq "py -3.10") {
        & py -3.10 -m venv $venvRoot
    } else {
        & $Python310 -m venv $venvRoot
    }
}

& $python -m pip install --upgrade pip
& $python -m pip install "argostranslate==1.11.0"
& $python -c "from argostranslate import package; package.update_package_index(); available=package.get_available_packages(); pairs=[('en','zh'),('zh','en')]; [package.install_from_path(next(item for item in available if item.from_code==source and item.to_code==target).download()) for source,target in pairs]"
Write-Host "Argos Translate installed: $env:ARGOS_PACKAGES_DIR"
