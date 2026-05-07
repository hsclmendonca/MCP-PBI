<#
.SYNOPSIS
    Core workflow to run MCP + Agent startup tasks.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\workspace\start-agent-mcp-core.ps1 -TargetProjectPath "C:\work\my-project" -OpenInCode
#>
[CmdletBinding()]
param(
    [string]$TargetProjectPath,
    [switch]$OpenInCode,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $PSScriptRoot -Parent
$mcpRoot = Split-Path $scriptDir -Parent  # Go up two levels to project root

function Open-VSCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathToOpen
    )

    $codeCmd = Get-Command code -ErrorAction SilentlyContinue
    if ($codeCmd) {
        & code $PathToOpen | Out-Null
        return $true
    }

    $candidates = @(
        (Join-Path $env:LocalAppData 'Programs\Microsoft VS Code\Code.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft VS Code\Code.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft VS Code\Code.exe')
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($exe in $candidates) {
        Start-Process -FilePath $exe -ArgumentList @($PathToOpen) | Out-Null
        return $true
    }

    return $false
}

Write-Host "`n=== Agent + MCP Local Startup ===" -ForegroundColor Cyan
Write-Host "MCP root: $mcpRoot" -ForegroundColor Gray

$bootstrap = Join-Path $mcpRoot 'scripts\setup\bootstrap.ps1'
$newWorkspaceScript = Join-Path $mcpRoot 'scripts\workspace\new-mcp-powerbi-workspace.ps1'

if (-not (Test-Path $bootstrap)) { throw "Missing bootstrap.ps1" }
if (-not (Test-Path $newWorkspaceScript)) { throw "Missing scripts/new-mcp-powerbi-workspace.ps1" }

if (-not $SkipBootstrap) {
    Write-Host "[1/3] Running bootstrap..." -ForegroundColor Yellow
    & $bootstrap -SkipReload
    if ($LASTEXITCODE -ne 0) { throw "bootstrap.ps1 failed with exit code $LASTEXITCODE" }
}
else {
    Write-Host "[1/3] Skipping bootstrap (-SkipBootstrap)." -ForegroundColor Yellow
}

Write-Host "[2/3] Preparing workspace..." -ForegroundColor Yellow

if ($TargetProjectPath) {
    Write-Host "Creating workspace with target project..." -ForegroundColor Yellow
    & $newWorkspaceScript -TargetProjectPath $TargetProjectPath -RunBootstrap -OpenInCode:$OpenInCode
    if ($LASTEXITCODE -ne 0) { throw "new-mcp-powerbi-workspace.ps1 failed with exit code $LASTEXITCODE" }
}
else {
    Write-Host "No target project specified. Staying in MCP starter workspace." -ForegroundColor Yellow
    if ($OpenInCode) {
        $opened = Open-VSCode -PathToOpen $mcpRoot
        if (-not $opened) {
            Write-Host "[WARN] VS Code CLI not found. Open manually: $mcpRoot" -ForegroundColor Yellow
        }
    }
}

Write-Host "[3/3] Ready." -ForegroundColor Green
Write-Host "Next in Copilot Chat (Agent mode):" -ForegroundColor Cyan
Write-Host "  1) 'Review my current Power BI model and tell me the main risks.'"
Write-Host "  2) If no model is connected: 'Connect to my open Power BI Desktop model and retry.'"
