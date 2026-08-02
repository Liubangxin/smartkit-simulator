param(
    [switch]$SkipBackend,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$electronDir = Join-Path $root "electron"

# ---- Helper: ensure 7za wrapper is in place ----
function Use-7zaWrapper {
    $sevenZipDir = Join-Path $electronDir "node_modules\7zip-bin\win\x64"
    $orig = Join-Path $sevenZipDir "7za_orig.exe"
    $wrapper = Join-Path $sevenZipDir "7za.exe"
    $wrapperSrc = Join-Path $electronDir "7za_wrapper.cs"

    # Already wrapped?
    if (Test-Path $orig) {
        Write-Host "[*] 7za wrapper already in place" -ForegroundColor Yellow
        return
    }

    Write-Host "[*] Setting up 7za wrapper..." -ForegroundColor Yellow

    # Compile wrapper if needed
    $wrapperExe = Join-Path $sevenZipDir "7za_wrapper.exe"
    if (-not (Test-Path $wrapperExe) -or (Get-Item $wrapperSrc).LastWriteTime -gt (Get-Item $wrapperExe).LastWriteTime) {
        $csc = "C:\WINDOWS\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
        if (-not (Test-Path $csc)) {
            throw "C# compiler not found at $csc. Install .NET Framework 4.x SDK."
        }
        Write-Host "  Compiling wrapper..." -ForegroundColor Gray
        & $csc /target:exe /out:$wrapperExe /reference:System.dll $wrapperSrc
        if ($LASTEXITCODE -ne 0) { throw "Compilation failed" }
    }

    # Rename original and copy wrapper
    Rename-Item $wrapper "7za_orig.exe"
    Copy-Item $wrapperExe $wrapper
    Write-Host "[+] 7za wrapper installed" -ForegroundColor Green
}

# ---- Helper: restore original 7za ----
function Restore-7zaOriginal {
    $sevenZipDir = Join-Path $electronDir "node_modules\7zip-bin\win\x64"
    $orig = Join-Path $sevenZipDir "7za_orig.exe"
    $wrapper = Join-Path $sevenZipDir "7za.exe"

    if (Test-Path $orig) {
        Remove-Item $wrapper -Force -ErrorAction SilentlyContinue
        Rename-Item $orig "7za.exe"
        Write-Host "[*] 7za original restored" -ForegroundColor Yellow
    }
}

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
    Use-7zaWrapper

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
    Restore-7zaOriginal
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
