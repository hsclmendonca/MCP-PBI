<#
.SYNOPSIS
    Test pbi-cli connection to Power BI Desktop with detailed diagnostics.
.DESCRIPTION
    Attempts to connect to Power BI Desktop and reports detailed status.
    Requires Power BI Desktop to be running with a .pbix file open.
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test\test-pbi-cli-connection.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'

Write-Host "`n=== PBI CLI Connection Test ===" -ForegroundColor Cyan

# 1. Check pbi-cli is installed
$pbi = Get-Command pbi -ErrorAction SilentlyContinue
if (-not $pbi) {
    Write-Host "[FAIL] pbi-cli not found in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] pbi-cli found: $($pbi.Source)" -ForegroundColor Green

# 2. Check Power BI Desktop is running
$pbiProcess = Get-Process -Name "PBIDesktop" -ErrorAction SilentlyContinue
if (-not $pbiProcess) {
    Write-Host "[FAIL] Power BI Desktop not running" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Power BI Desktop running (PID $($pbiProcess.Id))" -ForegroundColor Green

# 3. Attempt connection
Write-Host "`nAttempting connection..." -ForegroundColor Yellow
$connectResult = pbi connect 2>&1
$connectSuccess = $LASTEXITCODE -eq 0

if ($connectSuccess) {
    Write-Host "[OK] Connected to Power BI Desktop" -ForegroundColor Green
    
    # 4. Test model stats
    Write-Host "`nFetching model statistics..." -ForegroundColor Yellow
    $stats = pbi model stats 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Model stats retrieved:" -ForegroundColor Green
        $stats
    } else {
        Write-Host "[WARN] Could not retrieve model stats:" -ForegroundColor Yellow
        $stats
    }
    
    # 5. Test table list
    Write-Host "`nFetching tables..." -ForegroundColor Yellow
    $tables = pbi table list 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Tables retrieved:" -ForegroundColor Green
        $tables | Select-Object -First 10
    } else {
        Write-Host "[WARN] Could not retrieve tables:" -ForegroundColor Yellow
        $tables
    }
    
    Write-Host "`n=== Connection SUCCESSFUL ===" -ForegroundColor Green
    Write-Host "pbi-cli is fully operational. MCP server can now access your model." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "[FAIL] Connection failed" -ForegroundColor Red
    Write-Host "`nError output:" -ForegroundColor Yellow
    $connectResult
    
    Write-Host "`n⚠️  Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  - Ensure Power BI Desktop is open with a .pbix file" -ForegroundColor White
    Write-Host "  - Verify the .pbix file has at least one table" -ForegroundColor White
    Write-Host "  - Try closing and reopening Power BI Desktop" -ForegroundColor White
    Write-Host "  - Check that the file is not read-only or corrupted" -ForegroundColor White
    
    exit 1
}
