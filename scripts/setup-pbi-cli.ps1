<#
.SYNOPSIS
    Install and verify pbi-cli for Power BI development.
.DESCRIPTION
    Installs pbi-cli-tool via pipx (preferred) or pip, verifies the
    installation, and reports available commands.
#>
[CmdletBinding()]
param(
    [switch]$UsePip
)

$ErrorActionPreference = 'Stop'

Write-Host "`n=== pbi-cli Setup ===" -ForegroundColor Cyan

# Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[FAIL] Python not found. Install Python 3.10+ from python.org" -ForegroundColor Red
    exit 2
}

$pyVersion = & python --version 2>&1
Write-Host "[OK] $pyVersion" -ForegroundColor Green

# Check if pbi-cli is already installed
$pbi = Get-Command pbi -ErrorAction SilentlyContinue
if ($pbi) {
    Write-Host "[OK] pbi-cli already installed at: $($pbi.Source)" -ForegroundColor Green
    & pbi --version 2>$null
    Write-Host "`npbi-cli is ready. Run 'pbi connect' to connect to Power BI Desktop." -ForegroundColor Cyan
    exit 0
}

# Install
if (-not $UsePip) {
    $pipx = Get-Command pipx -ErrorAction SilentlyContinue
    if ($pipx) {
        Write-Host "Installing pbi-cli-tool via pipx..." -ForegroundColor Yellow
        & pipx install pbi-cli-tool
    } else {
        Write-Host "pipx not found. Falling back to pip..." -ForegroundColor Yellow
        $UsePip = $true
    }
}

if ($UsePip) {
    Write-Host "Installing pbi-cli-tool via pip..." -ForegroundColor Yellow
    & python -m pip install pbi-cli-tool --quiet
}

# Verify
$pbi = Get-Command pbi -ErrorAction SilentlyContinue
if (-not $pbi) {
    Write-Host "[WARN] 'pbi' command not found on PATH after install." -ForegroundColor Yellow
    Write-Host "Run this to find the Scripts directory:" -ForegroundColor Yellow
    Write-Host '  python -c "import site; print(site.getusersitepackages().replace(''site-packages'',''Scripts''))"'
    Write-Host "Add that path to your system PATH, then restart the terminal." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] pbi-cli installed successfully." -ForegroundColor Green
& pbi --version 2>$null
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Open Power BI Desktop with your .pbix file"
Write-Host "  2. Run: pbi connect"
Write-Host "  3. Use Copilot agents for model engineering"
