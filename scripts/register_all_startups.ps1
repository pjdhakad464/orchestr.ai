param(
    [string]$ListenHost = "127.0.0.1",
    [string]$PythonCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runnerScript = Join-Path $PSScriptRoot "run_engine.py"

if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at $runnerScript"
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$services = @(
    @{ Name = "Validator Engine"; Port = 8000; App = "app.main:app"; LogPrefix = "app.8000"; TaskName = "Playground Validator Engine" },
    @{ Name = "Title URL Lookup App"; Port = 8001; App = "title_url_lookup_app.main:app"; LogPrefix = "title_url_lookup_app.8001"; TaskName = "Playground Title URL Lookup App" },
    @{ Name = "Metacritic Calendar App"; Port = 8002; App = "metacritic_calendar_app.main:app"; LogPrefix = "metacritic_calendar_app.8002"; TaskName = "Playground Metacritic Calendar App" },
    @{ Name = "IMDb Lookup App"; Port = 8003; App = "imdb_lookup_app.main:app"; LogPrefix = "imdb_lookup_app.8003"; TaskName = "Playground IMDb Lookup App" }
)

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
Write-Host "Registering scheduled tasks using pythonw: $pythonwExe"

foreach ($service in $services) {
    $port = $service.Port
    $name = $service.Name
    $app = $service.App
    $logPrefix = $service.LogPrefix
    $taskName = $service.TaskName

    $stdoutLog = Join-Path $projectRoot "$($logPrefix).out.log"
    $stderrLog = Join-Path $projectRoot "$($logPrefix).err.log"

    $taskArgs = @(
        ('"{0}"' -f $runnerScript)
        "--host", $ListenHost
        "--port", $port.ToString()
        "--app", $app
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
        -TaskName $taskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Description "Starts the $name at logon and rechecks it every 5 minutes while the user session is active." `
        -Force | Out-Null

    Write-Host "Registered scheduled task '$taskName' for port $port." -ForegroundColor Green
}

Write-Host "`nAll startup tasks registered successfully." -ForegroundColor Green
