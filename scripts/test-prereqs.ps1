<#
.SYNOPSIS
    Validate workspace prerequisites for Power BI development.
.DESCRIPTION
    Checks that required tools, files, and configuration are in place
    before starting development work.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$errors = 0
$warnings = 0

Write-Host "`n=== Workspace Prerequisite Check ===" -ForegroundColor Cyan

# 1. Python
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    Write-Host "[OK] Python found" -ForegroundColor Green
}
else {
    Write-Host "[FAIL] Python not found - required for pbi-cli" -ForegroundColor Red
    $errors++
}

# 2. pbi-cli
$pbi = Get-Command pbi -ErrorAction SilentlyContinue
if ($pbi) {
    Write-Host "[OK] pbi-cli found at: $($pbi.Source)" -ForegroundColor Green
}
else {
    Write-Host "[WARN] pbi-cli not installed - run scripts/setup-pbi-cli.ps1" -ForegroundColor Yellow
    $warnings++
}

# 3. Required files for local MCP
$requiredFiles = @(
    ".vscode\\mcp.json",
    "scripts\\run-powerbi-mcp.cmd",
    "scripts\\powerbi-mcp-server.py",
    "scripts\\test-mcp-server.ps1",
    "scripts\\validate-mcp-local-only.ps1"
)

foreach ($file in $requiredFiles) {
    $fullPath = Join-Path $root $file
    if (Test-Path $fullPath) {
        Write-Host "[OK] Found $file" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] Missing $file" -ForegroundColor Red
        $errors++
    }
}

# 4. MCP local-only policy
$mcpConfigPath = Join-Path $root ".vscode\mcp.json"
if (Test-Path $mcpConfigPath) {
    try {
        $mcpConfig = Get-Content $mcpConfigPath -Raw | ConvertFrom-Json
        $remoteMcpFound = $false
        if ($mcpConfig.servers) {
            $serverNames = $mcpConfig.servers.PSObject.Properties.Name
            foreach ($serverName in $serverNames) {
                $server = $mcpConfig.servers.$serverName
                if ($server.type -eq "http") {
                    Write-Host "[FAIL] Remote MCP server configured: $serverName" -ForegroundColor Red
                    $errors++
                    $remoteMcpFound = $true
                }
                elseif ($server.url -and ($server.url -match '^https?://')) {
                    Write-Host "[FAIL] Remote MCP URL configured: $serverName" -ForegroundColor Red
                    $errors++
                    $remoteMcpFound = $true
                }
            }
        }
        if (-not $remoteMcpFound) {
            Write-Host "[OK] MCP configuration is local-only" -ForegroundColor Green
        }
    }
    catch {
        Write-Host "[WARN] Could not parse .vscode/mcp.json" -ForegroundColor Yellow
        $warnings++
    }
}
else {
    Write-Host "[INFO] .vscode/mcp.json not found" -ForegroundColor Gray
}

# 5. Power BI Desktop process (informational only)
$pbiDesktop = Get-Process -Name "PBIDesktop" -ErrorAction SilentlyContinue
if ($pbiDesktop) {
    Write-Host "[OK] Power BI Desktop is running" -ForegroundColor Green
}
else {
    Write-Host "[INFO] Power BI Desktop not running - open a .pbix before calling model tools" -ForegroundColor Gray
}

# Summary
Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($errors -gt 0) {
    Write-Host "$errors error(s), $warnings warning(s) - fix errors before proceeding." -ForegroundColor Red
    exit 1
}
elseif ($warnings -gt 0) {
    Write-Host "0 errors, $warnings warning(s) - workspace is usable with noted gaps." -ForegroundColor Yellow
    exit 0
}
else {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}
