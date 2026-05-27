param(
    [string]$ListenHost = "127.0.0.1",
    [int]$StartupWaitSeconds = 20,
    [string]$PythonCommand = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runnerScript = Join-Path $PSScriptRoot "run_engine.py"

if (-not (Test-Path $runnerScript)) {
    throw "Runner script not found at $runnerScript"
}

$services = @(
    @{ Name = "Validator Engine"; Port = 8000; App = "app.main:app"; LogPrefix = "app.8000" },
    @{ Name = "Title URL Lookup App"; Port = 8001; App = "title_url_lookup_app.main:app"; LogPrefix = "title_url_lookup_app.8001" },
    @{ Name = "Metacritic Calendar App"; Port = 8002; App = "metacritic_calendar_app.main:app"; LogPrefix = "metacritic_calendar_app.8002" },
    @{ Name = "IMDb Lookup App"; Port = 8003; App = "imdb_lookup_app.main:app"; LogPrefix = "imdb_lookup_app.8003" },
    @{ Name = "Instagram Comment News Filter"; Port = 8004; App = "instagram_comment_news_filter.main:app"; LogPrefix = "instagram_comment_news_filter.8004" },
    @{ Name = "Meta Instagram Comment Analyzer"; Port = 8010; App = "meta_instagram_comment_analyzer.main:app"; LogPrefix = "meta_instagram_comment_analyzer.8010" }
)

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

$pythonw = Resolve-PythonWindowlessCommand -PreferredCommand $PythonCommand
Write-Host "Using Pythonw executable: $pythonw"

$launchedCount = 0

foreach ($service in $services) {
    $port = $service.Port
    $name = $service.Name
    $app = $service.App
    $logPrefix = $service.LogPrefix

    if (Test-PortReady -LocalPort $port) {
        Write-Host "$name is already running on port $port." -ForegroundColor Yellow
        continue
    }

    Write-Host "Starting $name on port $port..."

    $stdoutLog = Join-Path $projectRoot "$($logPrefix).out.log"
    $stderrLog = Join-Path $projectRoot "$($logPrefix).err.log"

    if (Test-Path $stdoutLog) { Remove-Item $stdoutLog -Force }
    if (Test-Path $stderrLog) { Remove-Item $stderrLog -Force }

    $process = Start-Process `
        -FilePath $pythonw `
        -ArgumentList @(
            $runnerScript,
            "--host", $ListenHost,
            "--port", $port.ToString(),
            "--app", $app,
            "--stdout-log", $stdoutLog,
            "--stderr-log", $stderrLog
        ) `
        -WorkingDirectory $projectRoot `
        -PassThru

    $service["Process"] = $process
    $launchedCount++
}

if ($launchedCount -eq 0) {
    Write-Host "All services are already running." -ForegroundColor Green
    exit 0
}

Write-Host "Waiting up to $StartupWaitSeconds seconds for services to start..."

$allReady = $false
for ($second = 1; $second -le $StartupWaitSeconds; $second++) {
    Start-Sleep -Seconds 1
    $pending = 0
    foreach ($service in $services) {
        if (-not (Test-PortReady -LocalPort $service.Port)) {
            $pending++
        }
    }
    if ($pending -eq 0) {
        $allReady = $true
        break
    }
}

Write-Host "`nService Status Summary:" -ForegroundColor Cyan
$failedCount = 0
foreach ($service in $services) {
    $port = $service.Port
    $name = $service.Name
    if (Test-PortReady -LocalPort $port) {
        Write-Host "  [OK] $($name): http://$($ListenHost):$port" -ForegroundColor Green
    } else {
        $failedCount++
        $logPath = Join-Path $projectRoot "$($service.LogPrefix).err.log"
        Write-Host "  [FAILED] $name on port $port. Check error log: $logPath" -ForegroundColor Red
    }
}

if ($failedCount -gt 0) {
    exit 1
} else {
    Write-Host "`nAll services successfully started and listening." -ForegroundColor Green
}
