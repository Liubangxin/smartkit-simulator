param(
    [string]$PythonPath = ""
)

function Resolve-PythonCommand {
    if ($PythonPath) {
        return @($PythonPath)
    }
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @($venvPython)
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    throw "Python was not found. Install Python 3.12+ or pass -PythonPath C:\Path\To\python.exe"
}

$python = @(Resolve-PythonCommand)
$pythonArgs = @()
if ($python.Count -gt 1) {
    $pythonArgs = $python[1..($python.Count - 1)]
}
$pythonCommand = $python[0]

& $pythonCommand @pythonArgs -u (Join-Path $PSScriptRoot "simulator_gui.py")
