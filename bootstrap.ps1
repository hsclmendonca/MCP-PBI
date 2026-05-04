<#
.SYNOPSIS
    One-step bootstrap for local Power BI MCP server.
.DESCRIPTION
    Installs/validates prerequisites and prepares this workspace so VS Code
    can start the local MCP server automatically.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipReload
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSCommandPath -Parent

Write-Host "`n=== Power BI MCP Bootstrap (Local Only) ===" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $root ".vscode\mcp.json"))) {
    Write-Host "[FAIL] .vscode/mcp.json not found." -ForegroundColor Red
    exit 1
}

Write-Host "[1/5] Installing/checking pbi-cli..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\setup-pbi-cli.ps1")

Write-Host "[2/5] Validating local-only MCP policy..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\validate-mcp-local-only.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/5] Running prerequisite checks..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\test-prereqs.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/5] Testing MCP handshake..." -ForegroundColor Yellow
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "scripts\test-mcp-server.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipReload) {
    Write-Host "[5/5] Reloading VS Code window..." -ForegroundColor Yellow
    $codeCmd = Get-Command code -ErrorAction SilentlyContinue
    if ($codeCmd) {
        & code -r $root | Out-Null
    }
    else {
        Write-Host "[WARN] VS Code CLI not found. Reload window manually (Developer: Reload Window)." -ForegroundColor Yellow
    }
}

Write-Host "`nBootstrap complete." -ForegroundColor Green
Write-Host "Next: Open Copilot Chat in Agent mode and call tool: pbi_model_health_snapshot" -ForegroundColor Cyan
