# Power BI MCP Starter Instructions

This workspace is a lightweight local-only starter for a Power BI MCP server.

## Policy

- Use only the local MCP server defined in `.vscode/mcp.json`.
- Do not add remote MCP servers (`http` type or external URLs).
- Keep this repo simple and focused on startup reliability.

## Runtime

- MCP server: `scripts/powerbi-mcp-server.py`
- Launcher: `scripts/run-powerbi-mcp.cmd`
- Backend CLI: `pbi` (`pbi-cli-tool`)

## Default Behavior

1. Prefer read-only model inspection tools first.
2. Use `pbi_connect` only when Power BI Desktop is open.
3. Keep changes minimal and do not add unnecessary files.
4. Never include secrets in tracked files.
