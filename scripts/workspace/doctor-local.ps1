<#
.SYNOPSIS
    Run a full local diagnostics pass for Agent + MCP setup.
.DESCRIPTION
    Executes local-only validation, prerequisite checks, and MCP handshake tests.
    This script is safe for local use and does not add remote dependencies.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $PSScriptRoot -Parent
$root = Split-Path $scriptDir -Parent  # Go up two levels to project root

Write-Host "`n=== MCP Local Doctor ===" -ForegroundColor Cyan

$checks = @(
    @{ Name = 'Local-only policy'; Script = 'scripts\test\validate-mcp-local-only.ps1' },
    @{ Name = 'Workspace prerequisites'; Script = 'scripts\test\test-prereqs.ps1' },
    @{ Name = 'MCP handshake + tools'; Script = 'scripts\test\test-mcp-server.ps1' }
)

$failed = @()

for ($i = 0; $i -lt $checks.Count; $i++) {
    $check = $checks[$i]
    $scriptPath = Join-Path $root $check.Script

    if (-not (Test-Path $scriptPath)) {
        Write-Host "[FAIL] Missing script: $($check.Script)" -ForegroundColor Red
        $failed += $check.Name
        continue
    }

    Write-Host "[$($i + 1)/$($checks.Count)] $($check.Name)..." -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File $scriptPath

    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $($check.Name)" -ForegroundColor Red
        $failed += $check.Name
    }
    else {
        Write-Host "[OK] $($check.Name)" -ForegroundColor Green
    }
}

Write-Host "`n=== Doctor Summary ===" -ForegroundColor Cyan
if ($failed.Count -gt 0) {
    Write-Host "Failed checks: $($failed -join ', ')" -ForegroundColor Red
    Write-Host "Run bootstrap again and retry: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "All local diagnostics passed." -ForegroundColor Green
Write-Host "Next: open Copilot Chat in Agent mode and ask for a model review." -ForegroundColor Cyan
exit 0
