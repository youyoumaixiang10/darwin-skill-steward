$ErrorActionPreference = "Stop"

$pythonPath = $null
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) { $pythonPath = $pythonCommand.Source }

if (-not $pythonPath) {
    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCommand) { $pythonPath = $pyCommand.Source }
}

if (-not $pythonPath) {
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundledPython) { $pythonPath = $bundledPython }
}

if (-not $pythonPath) {
    Write-Error "Darwin requires Python 3. No Python executable was found."
    exit 1
}

$observer = Join-Path $env:PLUGIN_ROOT "scripts\observe.py"
if ([IO.Path]::GetFileName($pythonPath) -ieq "py.exe") {
    & $pythonPath -3 $observer
} else {
    & $pythonPath $observer
}
exit $LASTEXITCODE
