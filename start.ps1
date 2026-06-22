# Stop old NutritionTracker servers and start fresh on port 8000.
$ErrorActionPreference = "SilentlyContinue"
$Root = $PSScriptRoot
$Port = 8000
$PortsToClear = 8000, 8001, 8002, 8003, 8004, 8005

Write-Host "Stopping old NutritionTracker servers..."

Get-Process uvicorn -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  uvicorn PID $($_.Id)"
    Stop-Process -Id $_.Id -Force
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -like "*spawn_main*" -or
            $_.CommandLine -like "*uvicorn*main:app*" -or
            $_.CommandLine -like "*NutritionTracker*"
        )
    } |
    ForEach-Object {
        Write-Host "  $($_.Name) PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force
        cmd /c "taskkill /F /PID $($_.ProcessId) /T" 2>$null | Out-Null
    }

foreach ($listenPort in $PortsToClear) {
    Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
            $procId = $_.OwningProcess
            if ($procId -gt 0) {
                Write-Host "  port $listenPort -> PID $procId"
                Stop-Process -Id $procId -Force
                cmd /c "taskkill /F /PID $procId /T" 2>$null | Out-Null
            }
        }
}

Start-Sleep -Seconds 2

$stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($stillListening) {
    Write-Host "Port $Port still in use - force-killing listeners..."
    foreach ($conn in $stillListening) {
        $procId = $conn.OwningProcess
        if ($procId -gt 0) {
            cmd /c "taskkill /F /PID $procId /T" 2>$null | Out-Null
        }
    }
    Start-Sleep -Seconds 2
}

$uvicorn = Join-Path $Root "venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    Write-Error "venv not found. Run: python -m venv venv; .\venv\Scripts\pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting http://127.0.0.1:$Port (auto-reload on code changes)..."
Set-Location $Root
& $uvicorn main:app --host 127.0.0.1 --port $Port --reload
