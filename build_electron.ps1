param(
    [switch]$SkipBackend,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$electronDir = Join-Path $root "electron"
. (Join-Path $root "build_tools\SevenZipWrapper.ps1")

# ---- Main build ----
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " SmartKit Simulator - Electron Build" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Build Python backend
if (-not $SkipBackend) {
    Write-Host "[1/3] Building Python backend..." -ForegroundColor Cyan
    $backendScript = Join-Path $root "build_backend.ps1"
    if ($Clean) {
        & powershell -ExecutionPolicy Bypass -File $backendScript -Clean
    } else {
        & powershell -ExecutionPolicy Bypass -File $backendScript
    }
    if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
}

# Step 2: Set up 7za wrapper and build Electron
Write-Host "[2/3] Building Electron package..." -ForegroundColor Cyan

try {
    Use-7zaWrapper -ElectronDir $electronDir

    # Clean previous output
    $distDir = Join-Path $electronDir "dist"
    if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }

    # Run electron-builder with mirror
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
    Push-Location $electronDir
    try {
        $result = npx electron-builder --win portable 2>&1
        Write-Host $result
        if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
    } finally {
        Pop-Location
    }
} finally {
    Restore-7zaOriginal -ElectronDir $electronDir
}

# Step 3: Verify output
Write-Host "[3/3] Verifying output..." -ForegroundColor Cyan
$portableExe = Get-ChildItem (Join-Path $electronDir "dist\SmartKit-Simulator-*.exe") | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($portableExe) {
    $sizeMB = [math]::Round($portableExe.Length / 1MB, 1)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " BUILD SUCCESSFUL" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " Output: $($portableExe.FullName)" -ForegroundColor White
    Write-Host " Size:   $sizeMB MB" -ForegroundColor White
    Write-Host ""
    Write-Host "Double-click SmartKit-Simulator-1.0.0.exe to launch." -ForegroundColor Yellow
} else {
    throw "Portable exe not found in output directory"
}
