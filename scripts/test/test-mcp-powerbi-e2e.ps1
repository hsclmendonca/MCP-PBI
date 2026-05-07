<#
.SYNOPSIS
    End-to-end verification: MCP server identity + Power BI live model connectivity.
.DESCRIPTION
    Confirms that:
      1) VS Code MCP server id `powerbi` is configured in .vscode/mcp.json
      2) MCP handshake works against scripts/core/powerbi-mcp-server.py
      3) pbi-cli connects to open Power BI Desktop model and can read model stats

    This removes ambiguity for users asking:
      "Am I connected to mcp-pbi or powerbi-mcp-server?"
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $PSScriptRoot -Parent
$root = Split-Path $scriptDir -Parent

$mcpConfigPath = Join-Path $root ".vscode\mcp.json"
$handshakeScript = Join-Path $root "scripts\test\test-mcp-server.ps1"
$pbiExe = "C:\Users\ex_lmendonca\AppData\Local\Programs\Python\Python312\Scripts\pbi.exe"

Write-Host "`n=== MCP + Power BI End-to-End Verification ===" -ForegroundColor Cyan
Write-Host "Identity Standard: MCP-ID=powerbi | Alias=mcp-pbi | Server=powerbi-mcp-server" -ForegroundColor White

# 1) MCP config identity
if (-not (Test-Path $mcpConfigPath)) {
    Write-Host "[FAIL] MCP config not found: $mcpConfigPath" -ForegroundColor Red
    exit 2
}

$mcp = Get-Content $mcpConfigPath -Raw | ConvertFrom-Json
$server = $mcp.servers.powerbi
if (-not $server) {
    Write-Host "[FAIL] MCP server id 'powerbi' not found in .vscode/mcp.json" -ForegroundColor Red
    exit 2
}

Write-Host "[OK] MCP server id in VS Code config: powerbi" -ForegroundColor Green
Write-Host "     Command: $($server.command) $($server.args -join ' ')" -ForegroundColor White

# 2) MCP handshake
if (-not (Test-Path $handshakeScript)) {
    Write-Host "[FAIL] Handshake script not found: $handshakeScript" -ForegroundColor Red
    exit 2
}

Write-Host "`n[STEP] Running MCP handshake test..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File $handshakeScript
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] MCP handshake test failed." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] MCP handshake succeeded (powerbi-mcp-server is reachable)." -ForegroundColor Green

# 3) Power BI live model via pbi-cli
if (-not (Test-Path $pbiExe)) {
    Write-Host "[FAIL] pbi-cli executable not found: $pbiExe" -ForegroundColor Red
    exit 2
}

$pbid = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pbid) {
    Write-Host "[FAIL] Power BI Desktop is not running." -ForegroundColor Red
    Write-Host "       Open a PBIX/PBIP and run this test again." -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Power BI Desktop open: $($pbid.MainWindowTitle)" -ForegroundColor Green

Write-Host "`n[STEP] pbi-cli connect..." -ForegroundColor Yellow
$connectOut = cmd /d /c ('"{0}" connect 2>&1' -f $pbiExe)
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] pbi-cli connect failed:" -ForegroundColor Red
    Write-Host $connectOut
    exit 1
}
Write-Host "[OK] pbi-cli connected:" -ForegroundColor Green
Write-Host $connectOut

Write-Host "`n[STEP] pbi-cli model stats..." -ForegroundColor Yellow
$statsOut = cmd /d /c ('"{0}" model stats 2>&1' -f $pbiExe)
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] model stats failed:" -ForegroundColor Red
    Write-Host $statsOut
    exit 1
}
Write-Host "[OK] Live model is readable." -ForegroundColor Green
Write-Host $statsOut

Write-Host "`n=== E2E RESULT ===" -ForegroundColor Cyan
Write-Host "You are connected to:" -ForegroundColor White
Write-Host "  1) Identity: MCP-ID=powerbi | Alias=mcp-pbi | Server=powerbi-mcp-server" -ForegroundColor White
Write-Host "  2) Server implementation: scripts/core/powerbi-mcp-server.py" -ForegroundColor White
Write-Host "  3) Live Power BI model: via pbi-cli connect" -ForegroundColor White
Write-Host "`nStatus: PASS" -ForegroundColor Green
exit 0
