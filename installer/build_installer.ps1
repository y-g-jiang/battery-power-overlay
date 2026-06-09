param(
    [string]$Version = "v0.3.1"
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$releaseDir = Join-Path $repo "release"
$distDir = Join-Path $repo "installer\dist"
$workDir = Join-Path $repo "installer\build"
$specPath = Join-Path $repo "installer\BatteryPowerOverlaySetup.spec"
$setupPath = Join-Path $releaseDir "BatteryPowerOverlaySetup.exe"

New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

$payloadFiles = @(
    @{ Source = Join-Path $repo "battery_power_overlay.exe"; Dest = "." },
    @{ Source = Join-Path $repo "battery_power_overlay.json"; Dest = "." },
    @{ Source = Join-Path $repo "README.md"; Dest = "." },
    @{ Source = Join-Path $repo "NOTICE.md"; Dest = "." },
    @{ Source = Join-Path $PSScriptRoot "uninstall.cmd"; Dest = "installer" },
    @{ Source = Join-Path $repo "BatteryInfoView\BatteryInfoView.exe"; Dest = "BatteryInfoView" },
    @{ Source = Join-Path $repo "BatteryInfoView\BatteryInfoView_lng.ini"; Dest = "BatteryInfoView" }
)

foreach ($item in $payloadFiles) {
    if (-not (Test-Path -LiteralPath $item.Source)) {
        throw "Missing payload file: $($item.Source)"
    }
}

$datas = ($payloadFiles | ForEach-Object {
    "        ('$($_.Source.Replace('\', '\\'))', '$($_.Dest.Replace('\', '\\'))'),"
}) -join "`r`n"

$scriptPath = (Join-Path $PSScriptRoot "BatteryPowerOverlaySetup.py").Replace('\', '\\')
$distEscaped = $distDir.Replace('\', '\\')
$workEscaped = $workDir.Replace('\', '\\')

$spec = @"
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['$scriptPath'],
    pathex=[],
    binaries=[],
    datas=[
$datas
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BatteryPowerOverlaySetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"@

Set-Content -LiteralPath $specPath -Value $spec -Encoding UTF8

python -m PyInstaller --clean --noconfirm --distpath $distDir --workpath $workDir $specPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$built = Join-Path $distDir "BatteryPowerOverlaySetup.exe"
if (-not (Test-Path -LiteralPath $built)) {
    throw "Installer was not created: $built"
}

Copy-Item -LiteralPath $built -Destination $setupPath -Force
Get-Item -LiteralPath $setupPath
