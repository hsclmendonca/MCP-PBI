# Project Structure

## Overview

```
MCP PBI test/                          # Root: Power BI MCP Starter
├── START-LOCAL-MCP-AGENT.cmd          # 🎯 Main entry point (1-click startup)
├── bootstrap.ps1 → scripts/setup/     # (soft link for convenience)
├── install-from-link.ps1              # Install from GitHub repository ZIP
├── README.md                           # Project documentation
│
├── .vscode/                            # VS Code configuration
│   ├── mcp.json                        # MCP server definition (local-only)
│   ├── settings.json                   # Editor settings
│   ├── tasks.json                      # Tasks for bootstrap, test, doctor
│   └── extensions.json                 # Recommended extensions
│
├── scripts/                            # All automation scripts (organized by purpose)
│   ├── core/                           # Core MCP server
│   │   ├── powerbi-mcp-server.py       # MCP server (Python, stdio transport)
│   │   └── run-powerbi-mcp.cmd         # Windows launcher for MCP server
│   │
│   ├── setup/                          # Setup & installation
│   │   ├── bootstrap.ps1               # Main setup script (idempotent)
│   │   └── setup-pbi-cli.ps1           # Install pbi-cli-tool via pipx/pip
│   │
│   ├── test/                           # Validation & diagnostics
│   │   ├── test-mcp-server.ps1         # Test MCP initialize handshake
│   │   ├── test-prereqs.ps1            # Validate workspace prerequisites
│   │   └── validate-mcp-local-only.ps1 # Enforce local-only MCP policy
│   │
│   └── workspace/                      # Multi-root workspace management
│       ├── doctor-local.ps1            # Full local diagnostics (aggregates all tests)
│       ├── start-agent-mcp-core.ps1    # Agent + MCP startup workflow
│       └── new-mcp-powerbi-workspace.ps1 # Create .code-workspace with target project
│
├── pbip/                               # Power BI project (TMDL, model, etc.)
│   └── (model files after first export)
│
├── .github/                            # GitHub metadata
│   └── copilot-instructions.md         # Copilot agent instructions
│
├── .gitignore                          # Git ignore rules (PBIX, secrets, etc.)
└── .git/                               # Git repository
```

## Key Scripts by Use Case

### 🚀 First-Time Setup
**Windows:** Double-click `START-LOCAL-MCP-AGENT.cmd`
**PowerShell:** `scripts\setup\bootstrap.ps1`

Effects:
- Installs/validates `pbi-cli-tool`
- Validates local-only MCP configuration
- Tests Python, prerequisites, and MCP handshake
- Opens VS Code

### 🔧 Manual Bootstrap
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup\bootstrap.ps1
```

### 🏥 Diagnostics
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\workspace\doctor-local.ps1
```

Runs all validation checks:
1. Local-only MCP policy (`validate-mcp-local-only.ps1`)
2. Workspace prerequisites (`test-prereqs.ps1`)
3. MCP handshake + tools (`test-mcp-server.ps1`)

### 🛠️ Run Individual Tests
```powershell
# Check Python & pbi-cli
.\scripts\test\test-prereqs.ps1

# Check MCP policy (no HTTP/HTTPS servers)
.\scripts\test\validate-mcp-local-only.ps1

# Test MCP server initialize handshake
.\scripts\test\test-mcp-server.ps1
```

### 📦 Create Multi-Root Workspace
For working with a target project alongside the MCP starter:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\workspace\new-mcp-powerbi-workspace.ps1 `
  -TargetProjectPath "C:\path\to\my-project" `
  -OpenInCode
```

This creates a `.code-workspace` file that:
- Includes both the MCP starter folder AND your target project
- Allows VS Code to discover the local MCP server
- Shares the same MCP configuration across both folders

### 🤖 Start Agent + MCP
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\workspace\start-agent-mcp-core.ps1 `
  -TargetProjectPath "C:\path\to\my-project" `
  -OpenInCode
```

This:
1. Runs bootstrap
2. Creates workspace (if target provided)
3. Opens VS Code

## VS Code Tasks

All scripts can be executed via **Tasks** in VS Code (`Ctrl+Shift+P` → "Run Task"):

- `MCP: Bootstrap local server` → `scripts\setup\bootstrap.ps1`
- `MCP: Validate prerequisites` → `scripts\test\test-prereqs.ps1`
- `MCP: Validate local-only policy` → `scripts\test\validate-mcp-local-only.ps1`
- `MCP: Test Power BI server` → `scripts\test\test-mcp-server.ps1`
- `MCP: Start Agent+MCP (local)` → `scripts\workspace\start-agent-mcp-core.ps1`
- `MCP: Doctor (full local diagnostics)` → `scripts\workspace\doctor-local.ps1`

## Path Resolution

All PowerShell scripts correctly resolve to the **project root**, even when run from subdirectories:

```powershell
$scriptDir = Split-Path $PSScriptRoot -Parent
$root = Split-Path $scriptDir -Parent  # Project root
```

This ensures consistent behavior whether called from VS Code tasks, terminal, or subfolders.

## MCP Configuration

- **File:** `.vscode/mcp.json`
- **Type:** `stdio` (local, no external endpoints)
- **Server:** `scripts/core/run-powerbi-mcp.cmd`
- **Mode:** Read-only by default (`PBI_MCP_READ_ONLY=true`)

## Python Entry Point

`scripts/core/powerbi-mcp-server.py`:
- Handles JSON-RPC messages (newline-delimited)
- Binary mode on Windows (prevents CRLF corruption)
- Wraps `pbi-cli` commands
- Enforces read-only mode
- Optional debug logging (`PBI_MCP_DEBUG_LOG=1`)

## Environment

**Required:**
- Python 3.10+
- `pbi-cli-tool` (installed via `pipx` or `pip`)
- Power BI Desktop (for model operations)

**Optional:**
- VS Code with Copilot extension
- Git (for version control)

## Customization

- Edit `.vscode/settings.json` for MCP discovery settings
- Edit `.vscode/mcp.json` to add/modify MCP servers (keep local-only!)
- Add scripts to `scripts/` subdirectories as needed
- Update `STRUCTURE.md` when adding new scripts or folders
