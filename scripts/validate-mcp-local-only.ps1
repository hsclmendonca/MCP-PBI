<#
.SYNOPSIS
    Validate that workspace MCP configuration is local-only.
.DESCRIPTION
    Fails if any remote HTTP/HTTPS MCP server is configured.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$mcpPath = Join-Path $root ".vscode\mcp.json"

Write-Host "`n=== Validate MCP Local-Only Policy ===" -ForegroundColor Cyan

if (-not (Test-Path $mcpPath)) {
    Write-Host "[FAIL] Missing .vscode/mcp.json" -ForegroundColor Red
    exit 1
}

try {
    $mcp = Get-Content $mcpPath -Raw | ConvertFrom-Json
} catch {
    Write-Host "[FAIL] Invalid JSON in .vscode/mcp.json" -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}

if (-not $mcp.servers) {
    Write-Host "[WARN] No MCP servers configured." -ForegroundColor Yellow
    exit 0
}

$remoteServers = @()
$serverNames = $mcp.servers.PSObject.Properties.Name
foreach ($name in $serverNames) {
    $server = $mcp.servers.$name
    if ($server.type -eq "http") {
        $remoteServers += $name
        continue
    }
    if ($server.url -and ($server.url -match '^https?://')) {
        $remoteServers += $name
    }
}

if ($remoteServers.Count -gt 0) {
    Write-Host "[FAIL] Remote MCP servers found: $($remoteServers -join ', ')" -ForegroundColor Red
    Write-Host "Local-only policy violated." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] MCP configuration is local-only." -ForegroundColor Green
exit 0
