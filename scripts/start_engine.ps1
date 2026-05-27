param(
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000,
    [int]$StartupWaitSeconds = 20,
    [string]$PythonCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$stdoutLog = Join-Path $projectRoot "uvicorn.out.log"
$stderrLog = Join-Path $projectRoot "uvicorn.err.log"
$runnerScript = Join-Path $PSScriptRoot "run_engine.py"

function Test-PortReady {
    param([int]$LocalPort)

    try {
        return Test-NetConnection -ComputerName "127.0.0.1" -Port $LocalPort -InformationLevel Quiet -WarningAction SilentlyContinue
    }
    catch {
        return $false
    }
}

function Resolve-PythonCommand {
    param([string]$PreferredCommand)

    $candidates = [System.Collections.Generic.List[string]]::new()
    if ($PreferredCommand) {
        $candidates.Add($PreferredCommand)
    }
    if ($env:PLAYGROUND_PYTHON) {
        $candidates.Add($env:PLAYGROUND_PYTHON)
    }
    foreach ($commandName in @("python", "py")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $candidates.Add($command.Source)
        }
    }
    foreach ($knownPath in @(
        "C:\Users\Lenovo\AppData\Local\Programs\Python\Python314\python.exe",
        "C:\Users\Lenovo\AppData\Local\Python\bin\python.exe"
    )) {
        if (Test-Path $knownPath) {
            $candidates.Add($knownPath)
        }
    }

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            return $candidate
        }
    }

    throw "Python executable not found. Set PLAYGROUND_PYTHON or pass -PythonCommand."
}

function Resolve-PythonWindowlessCommand {
    param([string]$PreferredCommand)

    $python = Resolve-PythonCommand -PreferredCommand $PreferredCommand
    $pythonDirectory = Split-Path -Parent $python
    $pythonw = Join-Path $pythonDirectory "pythonw.exe"
    if (Test-Path $pythonw) {
        return $pythonw
    }

    throw "pythonw.exe not found next to $python. Install a standard Python build or update PLAYGROUND_PYTHON."
}

if (Test-PortReady -LocalPort $Port) {
    Write-Host "Engine already running on port $Port."
    exit 0
}

$pythonw = Resolve-PythonWindowlessCommand -PreferredCommand $PythonCommand
if (Test-Path $stdoutLog) {
    Remove-Item $stdoutLog -Force
}
if (Test-Path $stderrLog) {
    Remove-Item $stderrLog -Force
}

$process = Start-Process `
    -FilePath $pythonw `
    -ArgumentList @(
        $runnerScript,
        "--host", $ListenHost,
        "--port", $Port.ToString(),
        "--stdout-log", $stdoutLog,
        "--stderr-log", $stderrLog
    ) `
    -WorkingDirectory $projectRoot `
    -PassThru

for ($second = 0; $second -lt $StartupWaitSeconds; $second++) {
    Start-Sleep -Seconds 1

    if (Test-PortReady -LocalPort $Port) {
        Write-Host "Engine started successfully on http://$ListenHost`:$Port."
        exit 0
    }

    if ($process.HasExited) {
        throw "Engine process exited early with code $($process.ExitCode). Check $stderrLog."
    }
}

throw "Engine did not open port $Port within $StartupWaitSeconds seconds. Check $stdoutLog and $stderrLog."
