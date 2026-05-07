<#
.SYNOPSIS
    Install Power BI MCP starter from a repository ZIP link.
.DESCRIPTION
    Downloads a GitHub ZIP archive, extracts it to destination folder,
    and executes bootstrap.ps1.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install-from-link.ps1 -RepositoryZipUrl "https://github.com/ORG/REPO/archive/refs/heads/main.zip"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryZipUrl,

    [Parameter(Mandatory = $false)]
    [string]$Destination = "$env:USERPROFILE\\powerbi-mcp-starter"
)

$ErrorActionPreference = 'Stop'

# Validate URL: must be HTTPS and from github.com only
if ($RepositoryZipUrl -notmatch '^https://github\.com/') {
    Write-Host "[FAIL] URL must start with https://github.com/ for security reasons." -ForegroundColor Red
    Write-Host "Provided: $RepositoryZipUrl" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Install Power BI MCP Starter from Link ===" -ForegroundColor Cyan
Write-Host "Source: $RepositoryZipUrl" -ForegroundColor Gray
Write-Host "Destination: $Destination" -ForegroundColor Gray

$tempZip = Join-Path $env:TEMP ("powerbi-mcp-starter-" + [guid]::NewGuid().ToString() + ".zip")
$tempExtract = Join-Path $env:TEMP ("powerbi-mcp-starter-" + [guid]::NewGuid().ToString())

try {
    Write-Host "[1/4] Downloading ZIP..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $RepositoryZipUrl -OutFile $tempZip -UseBasicParsing

    Write-Host "[2/4] Extracting..." -ForegroundColor Yellow
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

    $repoRoot = Get-ChildItem $tempExtract -Directory | Select-Object -First 1
    if (-not $repoRoot) {
        throw "Could not detect extracted repository folder."
    }

    if (Test-Path $Destination) {
        Remove-Item -Recurse -Force $Destination
    }
    New-Item -ItemType Directory -Path $Destination | Out-Null

    Write-Host "[3/4] Copying project files..." -ForegroundColor Yellow
    Copy-Item -Path (Join-Path $repoRoot.FullName '*') -Destination $Destination -Recurse -Force

    $bootstrap = Join-Path $Destination "scripts\setup\bootstrap.ps1"
    if (-not (Test-Path $bootstrap)) {
        throw "scripts/setup/bootstrap.ps1 not found in downloaded repository."
    }

    Write-Host "[4/4] Running bootstrap..." -ForegroundColor Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File $bootstrap
    if ($LASTEXITCODE -ne 0) {
        throw "Bootstrap failed with exit code $LASTEXITCODE"
    }

    Write-Host "`nInstall completed." -ForegroundColor Green
    Write-Host "Project folder: $Destination" -ForegroundColor Cyan
}
finally {
    Remove-Item -Force $tempZip -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
}
