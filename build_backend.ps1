param(
    [string]$PythonPath = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# Resolve Python (prefer .venv)
function Resolve-PythonCommand {
    if ($PythonPath) {
        $py = $PythonPath
        if (Test-Path $py) { return @($py) }
        throw "Python not found at: $py"
    }
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return @($venvPython) }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @("py", "-3") }
    throw "Python not found. Install Python 3.12+ or create .venv, or pass -PythonPath."
}

$python = @(Resolve-PythonCommand)
$pythonExe = $python[0]
$pythonArgs = @()
if ($python.Count -gt 1) { $pythonArgs = $python[1..($python.Count - 1)] }

# Check dependencies
Write-Host "[1/4] Checking dependencies..." -ForegroundColor Cyan
$checkScript = @"
import importlib, sys
for pkg in ('flask', 'paramiko'):
    try: importlib.import_module(pkg)
    except ImportError: sys.exit(f'Missing: {pkg}\nRun: pip install -r requirements.txt')
print('OK')
"@
& $pythonExe @pythonArgs -c $checkScript
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Check PyInstaller
Write-Host "[2/4] Checking PyInstaller..." -ForegroundColor Cyan
$checkPyInstaller = @"
import importlib
try: importlib.import_module('PyInstaller'); print('OK')
except ImportError: sys.exit('Missing: pyinstaller\nRun: pip install pyinstaller')
"@
& $pythonExe @pythonArgs -c $checkPyInstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Clean previous build
$distBackend = Join-Path $root "dist\backend"
$specFile = Join-Path $root "simulator_gui.spec"
if ($Clean) {
    Write-Host "[*] Cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path $distBackend) { Remove-Item -Recurse -Force $distBackend }
    if (Test-Path $specFile) { Remove-Item -Force $specFile }
    $buildDir = Join-Path $root "build"
    if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
}

# Build backend with PyInstaller
Write-Host "[3/4] Building backend with PyInstaller..." -ForegroundColor Cyan

$pyinstallerArgs = @(
    "-m", "PyInstaller",
    "--onefile",
    "--windowed",
    "--clean",
    "--distpath", $distBackend,
    "--name", "simulator_gui",
    "--add-data", "index.html;.",
    "--add-data", "config.json;.",
    "simulator_gui.py"
)

$proc = Start-Process -FilePath $pythonExe -ArgumentList ($pythonArgs + $pyinstallerArgs) -NoNewWindow -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Host "[ERROR] PyInstaller build failed with exit code $($proc.ExitCode)" -ForegroundColor Red
    exit $proc.ExitCode
}

# Verify output
$exePath = Join-Path $distBackend "simulator_gui.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "[ERROR] Build output not found: $exePath" -ForegroundColor Red
    exit 1
}

# Clean up build artifacts (keep only the exe)
$buildDir = Join-Path $root "build"
if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
if (Test-Path $specFile) { Remove-Item -Force $specFile }

Write-Host "[4/4] Build complete!" -ForegroundColor Green
$exeSize = (Get-Item $exePath).Length / 1MB
Write-Host "  Output: $exePath" -ForegroundColor White
Write-Host "  Size:   $([math]::Round($exeSize, 1)) MB" -ForegroundColor White
Write-Host ""
Write-Host "Next: cd electron; npm run dist" -ForegroundColor Yellow
