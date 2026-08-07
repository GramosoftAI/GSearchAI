# PowerShell script to start GraphMind backend with detailed logging

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "🚀 Starting GraphMind Backend" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  LOG_LEVEL: DEBUG" -ForegroundColor DarkYellow
Write-Host "  POSTGRES_ECHO: true" -ForegroundColor DarkYellow
Write-Host "  Environment: development" -ForegroundColor DarkYellow
Write-Host ""
Write-Host "Starting uvicorn with detailed logging output..." -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Change to project directory
Set-Location $PSScriptRoot

# Start uvicorn with debug logging
# --log-level debug shows all request/response details
Write-Host "🔍 Logs will show:" -ForegroundColor Green
Write-Host "  ✓ Startup messages" -ForegroundColor Green
Write-Host "  ✓ Database operations" -ForegroundColor Green
Write-Host "  ✓ RLS policy creation" -ForegroundColor Green
Write-Host "  ✓ Every HTTP request/response" -ForegroundColor Green
Write-Host "  ✓ Authentication attempts" -ForegroundColor Green
Write-Host "  ✓ All errors with details" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Launching Memory API on port 4917 in a new window..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot'; python -m uvicorn app.memory.app.main:app --port 4917 --reload"



Write-Host "🚀 Launching Main API on port 4915..." -ForegroundColor Yellow
uvicorn app.main:app --reload --port 4915 --log-level debug

