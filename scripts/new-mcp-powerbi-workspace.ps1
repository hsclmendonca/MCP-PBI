<#
.SYNOPSIS
    Create a VS Code workspace that combines this MCP server project + any target project.
.DESCRIPTION
    Generates a .code-workspace file with two folders:
      1) This Power BI MCP starter (host of .vscode/mcp.json)
      2) Your target project

    This is the easiest way to reuse the same local MCP server setup for any project
    without copying files across repositories.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new-mcp-powerbi-workspace.ps1 -TargetProjectPath "C:\work\my-project" -Open
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetProjectPath,

    [Parameter(Mandatory = $false)]
    [string]$WorkspaceFile,

    [Alias('Open')]
    [switch]$OpenInCode,
    [switch]$RunBootstrap
)

$ErrorActionPreference = 'Stop'

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

$mcpRoot = Split-Path $PSScriptRoot -Parent
$target = Resolve-Path $TargetProjectPath -ErrorAction Stop
$targetPath = $target.Path

if (-not (Test-Path (Join-Path $mcpRoot '.vscode\mcp.json'))) {
    throw "MCP config not found in starter project: $mcpRoot\.vscode\mcp.json"
}

if (-not $WorkspaceFile) {
    $safeName = (Split-Path $targetPath -Leaf) + '-with-powerbi-mcp.code-workspace'
    $WorkspaceFile = Join-Path $targetPath $safeName
}

$folders = @(
    @{ path = $mcpRoot },
    @{ path = $targetPath }
)

$workspace = [ordered]@{
    folders  = $folders
    settings = [ordered]@{
        "chat.mcp.discovery.enabled" = [ordered]@{
            "claude-desktop"   = $true
            "windsurf"         = $true
            "cursor-global"    = $true
            "cursor-workspace" = $true
        }
    }
}

$json = $workspace | ConvertTo-Json -Depth 8
Set-Content -Path $WorkspaceFile -Value $json -Encoding UTF8

Write-Host "[OK] Workspace created: $WorkspaceFile" -ForegroundColor Green
Write-Host "Folders:" -ForegroundColor Cyan
Write-Host "  - $mcpRoot"
Write-Host "  - $targetPath"

if ($RunBootstrap) {
    Write-Host "Running MCP bootstrap in starter project..." -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $mcpRoot 'bootstrap.ps1') -SkipReload
    if ($LASTEXITCODE -ne 0) {
        throw "bootstrap.ps1 failed with exit code $LASTEXITCODE"
    }
}

if ($OpenInCode) {
    $opened = Open-VSCode -PathToOpen $WorkspaceFile
    if (-not $opened) {
        Write-Host "[WARN] VS Code CLI not found on PATH. Open manually: $WorkspaceFile" -ForegroundColor Yellow
        exit 0
    }
    Write-Host "[OK] Opened in VS Code." -ForegroundColor Green
}
else {
    Write-Host "Next step:" -ForegroundColor Cyan
    Write-Host "  code \"$WorkspaceFile\""
}
