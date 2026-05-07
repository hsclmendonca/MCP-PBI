# Power BI MCP Starter (Local-Only)

Starter local para subir um servidor MCP de Power BI no VS Code sem endpoint remoto.

## Overview

This project is designed to keep Power BI MCP usage simple and local:

- No remote MCP endpoints
- No external MCP auth flow
- Power BI actions routed through local `pbi-cli`
- VS Code starts the MCP server automatically via stdio

## Quick Start

Double-click this file from the repository root:

```text
START-LOCAL-MCP-AGENT.cmd
```

This is the recommended first-run experience for non-technical users.

It will:

1. Bootstrap dependencies and local checks
2. Validate MCP handshake and tool registration
3. Open VS Code ready for Agent + MCP usage

## PowerShell Alternative

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Bootstrap does the following:

1. Installs or validates `pbi-cli`
2. Validates the local-only MCP policy
3. Checks required files and prerequisites
4. Tests MCP handshake and tool registration
5. Reloads the VS Code window

## One-Command Agent + MCP Startup

To make setup and execution extremely simple, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-agent-mcp-core.ps1
```

To prepare and open a workspace with any target project:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-agent-mcp-core.ps1 -TargetProjectPath "C:\work\my-project" -OpenInCode
```

This startup command:

1. Runs bootstrap
2. Uses local-only MCP configuration
3. Creates a multi-root workspace when a target project is provided
4. Opens VS Code when `-OpenInCode` is used

## Recommended Workflow

The easiest way to use this MCP with any project is to open a multi-root workspace containing:

1. This MCP starter folder
2. Your target project folder

Generate that workspace with one command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new-mcp-powerbi-workspace.ps1 -TargetProjectPath "C:\work\my-project" -RunBootstrap -OpenInCode
```

This command:

1. Creates a `.code-workspace` file inside your target project
2. Includes both folders so VS Code can discover the MCP server
3. Optionally runs bootstrap
4. Opens the workspace in VS Code

## Daily Use

1. Open Power BI Desktop with a `.pbix`
2. Open the generated workspace in VS Code
3. Open Copilot Chat in Agent mode
4. Ask naturally for what you want to do

Examples:

- `Review my current Power BI model and tell me the main risks.`
- `What tables and measures do I have in the current PBIX?`
- `Check whether this DAX expression is valid: ...`
- `Compare the live model with the TMDL files in ./pbip/model`

You do not need to name a specific MCP tool in every prompt. The agent can select the tool based on intent.

Behind the scenes, the default orchestration is:

1. Try broad review tool first for analysis requests
2. If no active model connection exists, list connections
3. Connect to Power BI Desktop and retry the analysis

## Installation Options

Clone and bootstrap:

```powershell
git clone <YOUR_INTERNAL_GITHUB_REPO_URL>
cd <repo-folder>
powershell -NoProfile -ExecutionPolicy Bypass -File .\bootstrap.ps1
```

Or publish `install-from-link.ps1` and use a one-link install flow:

```powershell
irm <RAW_URL_TO_install-from-link.ps1> | iex
```

Then provide a repository ZIP URL such as:

```text
https://github.com/ORG/REPO/archive/refs/heads/main.zip
```

## Testing

Validate workspace prerequisites:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-prereqs.ps1
```

Validate the MCP server handshake and registered tools:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-mcp-server.ps1
```

Expected result:

1. Handshake succeeds
2. The server responds to `initialize`
3. The server lists its registered Power BI tools

Run all local diagnostics in one command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\doctor-local.ps1
```

Or run task: `MCP: Doctor (full local diagnostics)`.

## Am I Connected To The Right MCP?

If a user asks whether they are connected to `mcp-pbi` or `powerbi-mcp-server`, in this workspace they are the same local setup:

1. VS Code MCP server id: `powerbi` (defined in `.vscode/mcp.json`)
2. Local implementation: `scripts/core/powerbi-mcp-server.py`

Run this end-to-end check to confirm MCP identity + live Power BI model access in one shot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test\test-mcp-powerbi-e2e.ps1
```

Or run task: `MCP: Verify E2E (MCP + Power BI)`.

## High-Value MCP Tools

For high-level workflows, prefer these tools first:

1. `pbi_server_health` for runtime diagnostics (python, pbi-cli, local process state)
2. `pbi_connect_and_review` for automatic connect + model review in one call
3. `pbi_model_review` for structured model review when already connected

This follows a common best-practice pattern for MCP projects:

1. Health check first
2. Connection orchestration second
3. Domain analysis third

## Troubleshooting

If the server appears to hang waiting for `initialize`:

1. Do not start `scripts/powerbi-mcp-server.py` manually
2. Let VS Code start the server through `.vscode/mcp.json`
3. Run `bootstrap.ps1` again
4. Reload the VS Code window
5. Re-test with `scripts/test-mcp-server.ps1`

If Copilot does not seem to find the server:

1. Make sure the MCP starter folder is part of the open workspace
2. Prefer the generated `.code-workspace` flow
3. Keep Power BI Desktop open before asking model-related questions

## Core Files

- `.vscode/mcp.json` - MCP server configuration used by VS Code
- `bootstrap.ps1` - one-command onboarding
- `START-LOCAL-MCP-AGENT.cmd` - one-click startup for end users
- `install-from-link.ps1` - install-from-link flow
- `scripts/new-mcp-powerbi-workspace.ps1` - create a reusable workspace for any project
- `scripts/run-powerbi-mcp.cmd` - robust Windows launcher
- `scripts/powerbi-mcp-server.py` - MCP server implementation
- `scripts/setup-pbi-cli.ps1` - dependency setup
- `scripts/test-prereqs.ps1` - prerequisite validation
- `scripts/test-mcp-server.ps1` - MCP handshake and tools test
- `scripts/validate-mcp-local-only.ps1` - local-only policy validation

## Security Defaults

- Local-only MCP configuration
- No HTTP MCP servers
- Read-only mode enabled by default via `PBI_MCP_READ_ONLY=true`
