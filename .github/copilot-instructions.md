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

## Agent Orchestration Rules

When a user asks for broad model analysis without naming a specific tool:

1. Try `pbi_model_review` first.
2. If there is no active Power BI connection, call `pbi_connections_list`.
3. If a connection is available, call `pbi_connect` and retry the requested analysis.
4. Prefer returning a concise summary plus concrete next actions.

When a request is ambiguous, infer intent and pick tools automatically instead of asking
the user to provide exact MCP tool names.
