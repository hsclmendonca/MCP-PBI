# Power BI MCP Starter (Local-Only)

Minimal starter so anyone in the company can clone/download and run a local Power BI MCP server quickly.

This project is local-only:

- No remote MCP endpoints
- No external MCP auth flows
- Power BI tools run through local `pbi-cli`

## 1-Command Setup

From project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

What this does:

1. Installs/checks `pbi-cli`
2. Validates local-only MCP policy
3. Validates required files
4. Tests MCP handshake (`initialize` + `tools/list`)
5. Reloads VS Code window

## Use from GitHub Link

After publishing this repo, users can do either:

```powershell
git clone <YOUR_INTERNAL_GITHUB_REPO_URL>
cd <repo-folder>
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Or download ZIP from GitHub, extract, open folder, run `bootstrap.ps1`.

For one-link installation, publish `install-from-link.ps1` and run:

```powershell
irm <RAW_URL_TO_install-from-link.ps1> | iex
```

Then provide the repository ZIP URL when prompted, for example:

`https://github.com/ORG/REPO/archive/refs/heads/main.zip`

## Start Using MCP

1. Open Power BI Desktop with a `.pbix`.
2. Open this folder in VS Code.
3. Open Copilot Chat in Agent mode.
4. Ask for a tool call like:
   `Use pbi_model_health_snapshot on the current model`

## Core Files

- `.vscode/mcp.json` - local MCP server configuration
- `bootstrap.ps1` - one-command onboarding
- `install-from-link.ps1` - installer for "run from link" onboarding
- `scripts/run-powerbi-mcp.cmd` - robust launcher
- `scripts/powerbi-mcp-server.py` - MCP server implementation
- `scripts/setup-pbi-cli.ps1` - dependency setup
- `scripts/test-mcp-server.ps1` - protocol test
- `scripts/validate-mcp-local-only.ps1` - policy guardrail

## Security Defaults

- Local-only MCP (`.vscode/mcp.json` has no http servers)
- MCP discovery enabled to load workspace server
- Server read-only by default (`PBI_MCP_READ_ONLY=true`)
