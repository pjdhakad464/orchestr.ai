param(
    [string]$TaskName = "Playground Validator Engine",
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8000,
    [string]$PythonCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runnerScript = Join-Path $PSScriptRoot "run_engine.py"
if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at $runnerScript"
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$projectRoot = Split-Path -Parent $PSScriptRoot
$stdoutLog = Join-Path $projectRoot "uvicorn.out.log"
$stderrLog = Join-Path $projectRoot "uvicorn.err.log"

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

$pythonwExe = Resolve-PythonWindowlessCommand -PreferredCommand $PythonCommand
$taskArgs = @(
    ('"{0}"' -f $runnerScript)
    "--host", $ListenHost
    "--port", $Port.ToString()
    "--stdout-log", ('"{0}"' -f $stdoutLog)
    "--stderr-log", ('"{0}"' -f $stderrLog)
)

$action = New-ScheduledTaskAction -Execute $pythonwExe -Argument ($taskArgs -join " ") -WorkingDirectory $projectRoot
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Starts the Playground validator engine at logon and rechecks it every 5 minutes while the user session is active." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName' to start at logon and recheck the engine every 5 minutes."
