Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ports = @(8000, 8001, 8002, 8003)

Write-Host "Stopping all services on ports: $($ports -join ', ')..."

foreach ($port in $ports) {
    try {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($connections) {
            foreach ($conn in $connections) {
                $processId = $conn.OwningProcess
                if ($processId -gt 0) {
                    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    if ($process) {
                        Write-Host "Killing process $($process.Name) (PID: $processId) listening on port $port..."
                        Stop-Process -Id $processId -Force
                    }
                }
            }
        } else {
            Write-Host "No service running on port $port."
        }
    }
    catch {
        Write-Warning "Could not stop process on port $($port): $_"
    }
}

Write-Host "`nAll specified ports checked and closed." -ForegroundColor Green
