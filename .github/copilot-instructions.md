# Power BI MCP Starter Instructions

This workspace is a local-only MCP server for Power BI semantic model and report engineering.

## Policy

- Use only the local MCP server defined in `.vscode/mcp.json`.
- Do not add remote MCP servers (`http` type or external URLs).
- Never include secrets in tracked files.

## Runtime

- MCP server: `scripts/core/powerbi-mcp-server.py` (v3.2.0 — 54 tools)
- Launcher: `scripts/core/run-powerbi-mcp.cmd`
- Backend CLI: `pbi` (`pbi-cli-tool`)
- Write mode: enabled (`PBI_MCP_READ_ONLY=false` in `.vscode/mcp.json`)

## Tool Layers

### Semantic Model Layer — requires `pbi connect` (Power BI Desktop running)
- Inspection: `pbi_model_review`, `pbi_model_health_snapshot`, `pbi_workspace_context`, `pbi_table_list`, `pbi_column_list`, `pbi_measure_list`, `pbi_relationship_list`, `pbi_security_role_list`, `pbi_hierarchy_list`, `pbi_perspective_list`, `pbi_partition_list`
- DAX: `pbi_dax_execute`, `pbi_dax_validate`, `pbi_dax_clear_cache`
- Modification: `pbi_measure_create`, `pbi_column_set`, `pbi_relationship_create`, `pbi_security_role_create`
- Deployment: `pbi_export_tmdl`, `pbi_import_tmdl`, `pbi_diff_tmdl`, `pbi_export_tmsl`
- Diagnostics: `pbi_trace_start`, `pbi_trace_fetch`, `pbi_trace_stop`, `pbi_model_stats`

### Report Layer — works on PBIR files, NO live connection needed
- Report: `pbi_report_info`, `pbi_report_validate`, `pbi_report_create`, `pbi_report_reload`
- Pages: `pbi_page_list`, `pbi_page_add`, `pbi_page_delete`
- Visuals: `pbi_visual_list`, `pbi_visual_add`, `pbi_visual_get`, `pbi_visual_bind`, `pbi_visual_update`, `pbi_visual_delete`
- Filters: `pbi_filters_list`, `pbi_filters_add_categorical`, `pbi_filters_add_topn`, `pbi_filters_clear`
- Bookmarks: `pbi_bookmarks_list`, `pbi_bookmarks_add`, `pbi_bookmarks_delete`

### Infrastructure
- Connection: `pbi_connect`, `pbi_disconnect`, `pbi_connections_list`, `pbi_connect_and_review`
- Health: `pbi_server_health`
- Design inspection (no Desktop): `pbi_project_design_inspect`

## Agent Orchestration Rules

### Intent → Tool routing

**User asks to analyze, review, or audit the model:**
1. Call `pbi_model_review` (combines health + risks + measure audit).
2. If connection fails → call `pbi_connect_and_review` to auto-connect and retry.
3. If no Desktop running → call `pbi_project_design_inspect` with the `.pbip` path for offline inspection.

**User asks about report structure, pages, visuals, or filters:**
1. Use Report Layer tools — these work on PBIR files and do NOT require `pbi connect`.
2. Start with `pbi_report_info` or `pbi_page_list` to orient.
3. Then drill into `pbi_visual_list` → `pbi_visual_get` as needed.

**User asks to add or modify a visual/page/filter:**
1. Confirm the target `.pbip` report path.
2. Use `pbi_visual_add`, `pbi_page_add`, `pbi_filters_add_*` accordingly.
3. Call `pbi_report_reload` after edits to sync changes to Power BI Desktop.

**User asks to create or modify a measure/relationship:**
1. Ensure connected: call `pbi_connect` if not already done.
2. Use `pbi_measure_create`, `pbi_relationship_create`, or `pbi_column_set`.
3. Optionally validate DAX first with `pbi_dax_validate`.

**User asks about data, DAX, or performance:**
1. Use `pbi_dax_execute` for queries, `pbi_dax_validate` for syntax checks.
2. Use `pbi_trace_start` / `pbi_trace_fetch` / `pbi_trace_stop` for performance tracing.
3. Use `pbi_dax_clear_cache` before benchmarking.

**Connection is unavailable / Power BI Desktop not running:**
1. Return a degraded diagnostic via `pbi_workspace_context` (returns mode=degraded with next steps).
2. Suggest `pbi_project_design_inspect` for offline PBIP/TMDL inspection.
3. Never crash — always return helpful next actions.

### General principles
- Infer intent and pick tools automatically — do not ask the user to name exact tool names.
- Prefer concise summaries + concrete next actions over raw JSON dumps.
- Report Layer tools are always safe to call — they operate on local files.
- Semantic Model tools require an active connection — check with `pbi_connections_list` if unsure.
- After any model write, offer to validate or export a snapshot (`pbi_export_tmdl`).
