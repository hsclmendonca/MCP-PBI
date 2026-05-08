"""
Power BI MCP Server (v3)

A local MCP server that wraps pbi-cli for Power BI Desktop operations.
Transport: stdio with newline-delimited JSON-RPC (MCP standard).
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Windows binary mode fix: prevent CR/LF translation on stdin/stdout pipes.
# Without this, Python's C runtime translates \n → \r\n on stdout, which
# corrupts JSON-RPC messages and causes VS Code MCP host to hang.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    # Also suppress stderr to prevent any output leaking to the MCP pipe
    if not os.getenv("PBI_MCP_DEBUG_LOG", "").lower() in ("1", "true", "yes"):
        msvcrt.setmode(sys.stderr.fileno(), os.O_BINARY)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

READ_ONLY = os.getenv("PBI_MCP_READ_ONLY", "true").lower() in ("1", "true", "yes")
DEBUG = os.getenv("PBI_MCP_DEBUG_LOG", "").lower() in ("1", "true", "yes")

MUTATING_TOOLS = {
    # Semantic model
    "pbi_measure_create",
    "pbi_column_set",
    "pbi_relationship_create",
    "pbi_security_role_create",
    "pbi_import_tmdl",
    # Report layer
    "pbi_report_create",
    "pbi_page_add",
    "pbi_page_delete",
    "pbi_visual_add",
    "pbi_visual_update",
    "pbi_visual_delete",
    "pbi_visual_bind",
    "pbi_filters_add_categorical",
    "pbi_filters_add_topn",
    "pbi_filters_clear",
    "pbi_bookmarks_add",
    "pbi_bookmarks_delete",
    # Extended model
    "pbi_dax_clear_cache",
    "pbi_export_tmsl",
}

SERVER_INFO = {"name": "powerbi-mcp-server", "version": "3.2.0"}
MCP_IDENTITY = {
    "mcpServerId": "powerbi",
    "alias": "mcp-pbi",
    "serverName": SERVER_INFO["name"],
    "serverVersion": SERVER_INFO["version"],
}
CAPABILITIES = {"tools": {}}

# ---------------------------------------------------------------------------
# Logging (stderr → file when debug, devnull otherwise)
# ---------------------------------------------------------------------------

def _setup_logging():
    if not DEBUG:
        sys.stderr = open(os.devnull, "w")
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server.log")
    try:
        sys.stderr = open(log_path, "a", encoding="utf-8")
    except OSError:
        pass

def log(msg):
    if DEBUG:
        print(msg, file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# MCP Transport: newline-delimited JSON-RPC over stdio
# ---------------------------------------------------------------------------
# VS Code 1.117+ sends one JSON object per line on stdin, terminated by \n.
# We respond with one JSON object per line on stdout, terminated by \n.
# No Content-Length headers. Binary mode on Windows to avoid CR/LF issues.

def read_message():
    """Read one JSON-RPC message (one line) from stdin."""
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            return None  # EOF
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue  # skip blank lines
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            log(f"[WARN] non-JSON line ignored: {line[:120]}")
            continue


def write_message(obj):
    """Write one JSON-RPC message (one line) to stdout."""
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(line.encode("utf-8"))
    sys.stdout.buffer.flush()


def send_result(req_id, result):
    write_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def send_error(req_id, code, message):
    write_message({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------------------
# pbi-cli helpers
# ---------------------------------------------------------------------------

def run_pbi(*args, timeout=30):
    """Run pbi-cli and return (ok, output_text)."""
    if shutil.which("pbi") is None:
        return False, "pbi-cli not found in PATH. Install: pipx install pbi-cli-tool"

    cmd = ["pbi", "--json"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
        out = r.stdout.strip()
        if r.returncode != 0:
            err = r.stderr.strip() or out or f"pbi-cli exit code {r.returncode}"
            return False, err
        return True, out
    except FileNotFoundError:
        return False, "pbi-cli not found. Install: pipx install pbi-cli-tool"
    except subprocess.TimeoutExpired:
        return False, f"pbi-cli timed out ({timeout}s)"
    except Exception as e:
        return False, str(e)


def run_pbi_json(*args, timeout=30):
    ok, out = run_pbi(*args, timeout=timeout)
    if not ok:
        return False, None, out
    try:
        return True, json.loads(out), out
    except json.JSONDecodeError:
        return True, None, out


def extract_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("items", "data", "results", "tables", "columns", "measures", "relationships", "roles"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    return []


def _to_bool(v, default=False):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return default


def is_connection_error(text):
    t = (text or "").lower()
    signals = (
        "not connected",
        "no active connection",
        "connect to",
        "power bi desktop is not running",
        "connection",
    )
    return any(s in t for s in signals)


def is_powerbi_desktop_running():
    if sys.platform != "win32":
        return None
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq PBIDesktop.exe"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        output = (r.stdout or "") + "\n" + (r.stderr or "")
        return "PBIDesktop.exe" in output
    except Exception:
        return None


def extract_connection_candidates(payload):
    candidates = []
    items = extract_items(payload)
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("dataSource", "datasource", "data_source", "server", "address", "endpoint"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    # preserve order while removing duplicates
    return list(dict.fromkeys(candidates))


def build_model_review_payload(ctx):
    review = {
        "summary": ctx.get("summary", {}),
        "qualitySignals": ctx.get("qualitySignals", {}),
        "relationshipRisks": extract_items(ctx.get("sources", {}).get("relationships")),
        "measurePlacement": ctx.get("summary", {}).get("topMeasureTables", []),
        "recommendations": [],
    }
    signals = review["qualitySignals"]
    if signals.get("manyToManyRelationships", 0) > 0:
        review["recommendations"].append("Review many-to-many relationships and confirm they are intentional.")
    if signals.get("bidirectionalRelationships", 0) > 0:
        review["recommendations"].append("Review bidirectional filters and reduce them when possible.")
    if signals.get("inactiveRelationships", 0) > 0:
        review["recommendations"].append("Inspect inactive relationships and confirm that measures rely on them intentionally.")
    if not signals.get("rolesDefined", False):
        review["recommendations"].append("No security roles found. Confirm whether RLS is required.")
    if not review["recommendations"]:
        review["recommendations"].append("No obvious structural risks detected in the current high-level review.")
    return review


# ---------------------------------------------------------------------------
# Workspace context builders
# ---------------------------------------------------------------------------

def build_workspace_context():
    commands = {
        "modelStats": ("model", "stats"),
        "tables": ("table", "list"),
        "measures": ("measure", "list"),
        "relationships": ("relationship", "list"),
        "roles": ("security-role", "list"),
    }
    ctx = {"readOnlyMode": READ_ONLY, "sources": {}, "summary": {}, "qualitySignals": {}}
    for label, cmd in commands.items():
        ok, payload, raw = run_pbi_json(*cmd)
        if not ok:
            return False, f"Failed {label}: {raw}"
        ctx["sources"][label] = payload if payload is not None else {"raw": raw}

    tables = extract_items(ctx["sources"].get("tables"))
    measures = extract_items(ctx["sources"].get("measures"))
    rels = extract_items(ctx["sources"].get("relationships"))
    roles = extract_items(ctx["sources"].get("roles"))

    mc = {}
    for m in measures:
        t = m.get("table") or m.get("tableName") or m.get("table_name") or "Unknown"
        mc[t] = mc.get(t, 0) + 1

    m2m = bidi = inactive = 0
    for r in rels:
        card = str(r.get("cardinality") or r.get("relationshipCardinality") or "").lower()
        dirn = str(r.get("direction") or r.get("crossFilteringBehavior") or "").lower()
        act = r.get("isActive")
        if "many-to-many" in card or "m:m" in card:
            m2m += 1
        if "both" in dirn or "bi" in dirn:
            bidi += 1
        if act is not None and not _to_bool(act, True):
            inactive += 1

    ctx["summary"] = {
        "tableCount": len(tables),
        "measureCount": len(measures),
        "relationshipCount": len(rels),
        "roleCount": len(roles),
        "topMeasureTables": sorted(
            [{"table": k, "measureCount": v} for k, v in mc.items()],
            key=lambda x: x["measureCount"], reverse=True
        )[:10],
    }
    ctx["qualitySignals"] = {
        "manyToManyRelationships": m2m,
        "bidirectionalRelationships": bidi,
        "inactiveRelationships": inactive,
        "rolesDefined": len(roles) > 0,
    }
    return True, ctx


def inspect_pbip_project(project_path):
    """Inspect a local PBIP/TMDL project without requiring a live Power BI connection."""
    if not project_path:
        return {"ok": False, "error": "projectPath is required."}

    p = Path(project_path)
    if not p.exists():
        return {"ok": False, "error": f"Path not found: {project_path}"}

    base_dir = p.parent if p.is_file() else p
    semantic_dir = None

    if p.is_dir() and p.name.endswith(".SemanticModel"):
        semantic_dir = p
    else:
        semantic_candidates = sorted(base_dir.glob("*.SemanticModel"))
        if semantic_candidates:
            semantic_dir = semantic_candidates[0]

    if semantic_dir is None:
        return {
            "ok": False,
            "error": "No .SemanticModel directory found near projectPath.",
            "projectPath": str(p),
        }

    tmdl_files = [f for f in semantic_dir.rglob("*.tmdl") if f.is_file()]
    table_files = [f for f in tmdl_files if "tables" in [x.lower() for x in f.parts]]

    measure_count = 0
    table_names = []
    for tf in table_files:
        table_names.append(tf.stem)
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        measure_count += len(re.findall(r"(?im)^\s*measure\s+", content))

    return {
        "ok": True,
        "mode": "design-only",
        "projectPath": str(p),
        "semanticModelPath": str(semantic_dir),
        "tableCountFromFiles": len(table_files),
        "measureCountFromTmdl": measure_count,
        "sampleTables": sorted(table_names)[:20],
        "notes": [
            "This is a local design inspection from PBIP/TMDL files.",
            "No live model connection is required for this output.",
        ],
    }


def build_degraded_context(reason, project_path=None):
    """Return resilient diagnostics when live model context is unavailable."""
    connections = []
    ok_conn, payload, raw_conn = run_pbi_json("connections", "list")
    if ok_conn:
        connections = extract_items(payload)

    degraded = {
        "mode": "degraded",
        "reason": reason,
        "powerBIDesktopRunning": is_powerbi_desktop_running(),
        "availableConnections": connections,
        "nextActions": [
            "Open a PBIX/PBIP in Power BI Desktop and wait for model load.",
            "Retry pbi_connect then call model tools.",
            "Use pbi_project_design_inspect with projectPath to inspect local design without live model.",
        ],
    }

    if project_path:
        degraded["designInspection"] = inspect_pbip_project(project_path)

    if not ok_conn:
        degraded["connectionsListError"] = raw_conn

    return degraded


def make_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _report_args(args):
    """Build common report-layer CLI flags from tool arguments."""
    ca = []
    if args.get("reportPath"):
        ca += ["--report", args["reportPath"]]
    return ca


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {"name": "pbi_server_health", "description": "Return local MCP runtime health (python, pbi-cli, read-only mode, and Power BI Desktop process state). Use for diagnostics before model operations.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_connect", "description": "Connect to a running Power BI Desktop instance. Use when the user asks to connect, attach to an open PBIX, or start working with the current model.", "inputSchema": {"type": "object", "properties": {"dataSource": {"type": "string", "description": "Optional localhost:port."}}}},
    {"name": "pbi_disconnect", "description": "Disconnect from Power BI Desktop. Use when the user asks to close or reset the current Power BI connection.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_connections_list", "description": "List available Power BI Desktop connections. Use first when no connection is active or when the user asks which desktop instances are available.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_model_stats", "description": "Get model statistics such as counts of tables, measures, relationships, and roles. Use for quick model size summaries.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_table_list", "description": "List all tables in the semantic model. Use when the user asks what tables exist or wants to inspect model structure.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_column_list", "description": "List columns in a specific table. Use after the table is known and the user wants to inspect fields, types, or available columns.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string", "description": "Table name."}}, "required": ["table"]}},
    {"name": "pbi_measure_list", "description": "List all measures with DAX expressions. Use when the user asks to inspect, review, audit, or search existing measures.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_relationship_list", "description": "List all relationships. Use when the user asks about joins, model links, filter flow, or relationship inventory.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_security_role_list", "description": "List security roles (RLS/OLS). Use when the user asks about row-level security, object security, or model access roles.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_workspace_context", "description": "Full model snapshot combining stats, tables, measures, relationships, and roles. Use when the user asks for a broad overview, context, or complete inspection of the model.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_model_health_snapshot", "description": "Health summary with quality signals and recommendations. Best first tool for requests like analyze this model, review this report model, identify issues, or summarize modeling risks.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_relationship_risk_context", "description": "Relationship risk analysis. Use when the user asks about many-to-many, bidirectional filters, inactive relationships, or relationship problems.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_measure_audit_context", "description": "Measure placement audit with raw measures and concentration by table. Use when the user asks if measures are well organized or wants measure governance feedback.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_model_review", "description": "High-level review of the current Power BI model combining health, relationship risk, and measure audit in one tool. Best choice for broad natural-language requests like review my model, analyze this semantic model, or tell me what is wrong here.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_connect_and_review", "description": "Auto-connect workflow for broad analysis: tries to connect to Power BI Desktop and then returns model review. Use when user asks to analyze but connection may not be active.", "inputSchema": {"type": "object", "properties": {"dataSource": {"type": "string", "description": "Optional localhost:port for explicit connection target."}, "projectPath": {"type": "string", "description": "Optional PBIP/TMDL path for design-only fallback when no live model is available."}}}},
    {"name": "pbi_project_design_inspect", "description": "Inspect PBIP/TMDL project design from local files without requiring live model connection. Use when the model is not connected, partially loaded, or in imperfect environments.", "inputSchema": {"type": "object", "properties": {"projectPath": {"type": "string", "description": "Path to .pbip file, .SemanticModel folder, or project folder."}}, "required": ["projectPath"]}},
    {"name": "pbi_dax_execute", "description": "Execute a DAX query. Use when the user provides a complete DAX query to run against the connected model.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "DAX query."}}, "required": ["query"]}},
    {"name": "pbi_dax_validate", "description": "Validate a DAX expression without creating anything. Use when the user asks if an expression is valid or wants syntax/semantic validation.", "inputSchema": {"type": "object", "properties": {"expression": {"type": "string", "description": "DAX expression."}}, "required": ["expression"]}},
    {"name": "pbi_measure_create", "description": "Create a DAX measure. Use only when the user clearly wants to add a new measure and provides or approves the expression.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string"}, "name": {"type": "string"}, "expression": {"type": "string"}, "formatString": {"type": "string"}, "displayFolder": {"type": "string"}}, "required": ["table", "name", "expression"]}},
    {"name": "pbi_column_set", "description": "Set a column property. Use when the user wants to change metadata such as formatting, visibility, or column behavior.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string"}, "column": {"type": "string"}, "property": {"type": "string"}, "value": {"type": "string"}}, "required": ["table", "column", "property", "value"]}},
    {"name": "pbi_relationship_create", "description": "Create a relationship between two tables. Use when the user explicitly asks to relate model tables and provides both sides.", "inputSchema": {"type": "object", "properties": {"fromTable": {"type": "string"}, "fromColumn": {"type": "string"}, "toTable": {"type": "string"}, "toColumn": {"type": "string"}}, "required": ["fromTable", "fromColumn", "toTable", "toColumn"]}},
    {"name": "pbi_security_role_create", "description": "Create a security role. Use when the user explicitly asks to add RLS or OLS roles.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "filterExpression": {"type": "string"}}, "required": ["name"]}},
    {"name": "pbi_export_tmdl", "description": "Export the live model as TMDL on disk. Use when the user asks to version, inspect, or persist the current model definition.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Output directory."}}}},
    {"name": "pbi_import_tmdl", "description": "Import TMDL into the live model. Use only for explicit model deployment or synchronization requests.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "pbi_diff_tmdl", "description": "Diff live model versus TMDL on disk. Use when the user asks what changed or wants to compare the desktop model with files.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "pbi_trace_start", "description": "Start diagnostic trace. Use for troubleshooting performance or low-level Power BI activity.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_trace_fetch", "description": "Fetch trace events from an active diagnostic trace. Use after starting a trace.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_trace_stop", "description": "Stop diagnostic trace. Use after diagnostics are complete.", "inputSchema": {"type": "object", "properties": {}}},
    # --- Report Layer (PBIR — no live connection needed) ---
    {"name": "pbi_report_info", "description": "Get structure and metadata of a PBIR report including pages and report-level settings. Does NOT require Power BI Desktop to be running. Use when the user asks about report structure or pages.", "inputSchema": {"type": "object", "properties": {"reportPath": {"type": "string", "description": "Path to .pbip file or report folder. Auto-detected from working directory if omitted."}}}},
    {"name": "pbi_report_validate", "description": "Validate PBIR report structure for correctness. Use before publishing or after edits to catch structural issues. No live connection needed.", "inputSchema": {"type": "object", "properties": {"reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}}},
    {"name": "pbi_report_create", "description": "Create a new PBIR report project. Use when the user asks to scaffold or create a new Power BI report file.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Report project name."}, "reportPath": {"type": "string", "description": "Directory to create the report in."}}, "required": ["name"]}},
    {"name": "pbi_report_reload", "description": "Reload the PBIR report in Power BI Desktop after file edits. Use after modifying PBIR files to sync changes back to the Desktop UI.", "inputSchema": {"type": "object", "properties": {"reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}}},
    # Pages
    {"name": "pbi_page_list", "description": "List all pages in a PBIR report. Use when the user asks what pages or tabs exist in a report. No live connection needed.", "inputSchema": {"type": "object", "properties": {"reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}}},
    {"name": "pbi_page_add", "description": "Add a new page to a PBIR report. Use when the user asks to create a new report page or tab.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Page display name."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["name"]}},
    {"name": "pbi_page_delete", "description": "Delete a page from a PBIR report. Use when the user asks to remove a specific report page.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name to delete."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page"]}},
    # Visuals
    {"name": "pbi_visual_list", "description": "List all visuals on a report page. Use when the user asks what charts, tables, cards, or visuals are on a specific page.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page"]}},
    {"name": "pbi_visual_add", "description": "Add a visual to a report page. Supports 32 visual types: barChart, lineChart, columnChart, tableEx, matrix, card, slicer, donutChart, pieChart, scatterChart, waterfallChart, kpi, gauge, treemap, funnel, ribbonChart, areaChart, multiRowCard, and more. Use when the user asks to add a chart or visual.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "type": {"type": "string", "description": "Visual type (e.g. barChart, lineChart, columnChart, tableEx, matrix, card, slicer)."}, "x": {"type": "number", "description": "X position in pixels."}, "y": {"type": "number", "description": "Y position in pixels."}, "width": {"type": "number", "description": "Width in pixels."}, "height": {"type": "number", "description": "Height in pixels."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "type"]}},
    {"name": "pbi_visual_get", "description": "Get details of a specific visual on a page including its configuration, bound fields, and formatting. Use to inspect a visual before editing it.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "visual": {"type": "string", "description": "Visual ID (from pbi_visual_list)."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "visual"]}},
    {"name": "pbi_visual_bind", "description": "Bind a measure or column to a visual field well (Values, Axis, Legend, etc.). Use when the user asks to add data to a visual, connect a measure to a chart, or set what data a visual displays.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "visual": {"type": "string", "description": "Visual ID."}, "table": {"type": "string", "description": "Table name."}, "column": {"type": "string", "description": "Column or measure name."}, "role": {"type": "string", "description": "Field well role (e.g. Values, Axis, Legend, Category, Details)."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "visual", "table", "column"]}},
    {"name": "pbi_visual_update", "description": "Update a visual property or setting. Use when the user asks to change visual formatting, title, colors, borders, or display options.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "visual": {"type": "string", "description": "Visual ID."}, "property": {"type": "string", "description": "Property path to update."}, "value": {"type": "string", "description": "New value."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "visual", "property", "value"]}},
    {"name": "pbi_visual_delete", "description": "Delete a visual from a report page. Use when the user asks to remove a chart, card, or any visual element from a page.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "visual": {"type": "string", "description": "Visual ID."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "visual"]}},
    # Filters
    {"name": "pbi_filters_list", "description": "List all filters on a report page or visual. Use when the user asks to see what filters are applied or wants to audit report filters.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "visual": {"type": "string", "description": "Optional visual ID to scope to a specific visual."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page"]}},
    {"name": "pbi_filters_add_categorical", "description": "Add a categorical filter to a report page. Use when the user asks to filter by specific values like region, product, or category name.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "table": {"type": "string", "description": "Table name."}, "column": {"type": "string", "description": "Column name."}, "values": {"type": "string", "description": "Comma-separated values to include in filter."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "table", "column", "values"]}},
    {"name": "pbi_filters_add_topn", "description": "Add a Top N filter to a report page. Use when the user asks to show only the top N products, customers, or items ranked by a measure.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "table": {"type": "string", "description": "Table name."}, "column": {"type": "string", "description": "Column to rank."}, "n": {"type": "number", "description": "Number of top items to show."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page", "table", "column", "n"]}},
    {"name": "pbi_filters_clear", "description": "Clear all filters from a report page. Use when the user asks to remove or reset all filters on a specific page.", "inputSchema": {"type": "object", "properties": {"page": {"type": "string", "description": "Page name."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["page"]}},
    # Bookmarks
    {"name": "pbi_bookmarks_list", "description": "List all bookmarks in a report. Use when the user asks what bookmarks or saved views exist in a report.", "inputSchema": {"type": "object", "properties": {"reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}}},
    {"name": "pbi_bookmarks_add", "description": "Add a bookmark capturing the current report state. Use when the user asks to save a view, create a navigation bookmark, or record a specific filter state.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Bookmark display name."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["name"]}},
    {"name": "pbi_bookmarks_delete", "description": "Delete a bookmark from a report. Use when the user asks to remove or clean up a specific bookmark.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Bookmark name to delete."}, "reportPath": {"type": "string", "description": "Path to .pbip file or report folder."}}, "required": ["name"]}},
    # Extended Model
    {"name": "pbi_partition_list", "description": "List all partitions for a table including M queries. Use when the user asks about data refresh, partitions, incremental refresh configuration, or M queries for a table.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string", "description": "Table name."}}, "required": ["table"]}},
    {"name": "pbi_hierarchy_list", "description": "List all hierarchies in the semantic model. Use when the user asks about drilldown paths, date hierarchies, or navigation structures in the model.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_perspective_list", "description": "List all perspectives defined in the model. Use when the user asks how the model is exposed to different audiences or roles, or wants to audit perspectives.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_dax_clear_cache", "description": "Clear the DAX query cache in Power BI Desktop. Use before benchmarking query performance or when results seem stale after model changes.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_export_tmsl", "description": "Export the live model as TMSL (Tabular Model Scripting Language JSON). Use when the user needs the raw model JSON for Analysis Services scripting, deployment automation, or deep model inspection.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Output file path for the TMSL JSON."}}}},
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def handle_tool_call(name, args):
    args = args or {}
    if READ_ONLY and name in MUTATING_TOOLS:
        return make_result("Blocked: read-only mode (PBI_MCP_READ_ONLY=true).", is_error=True)

    if name == "pbi_server_health":
        pbi_path = shutil.which("pbi")
        health = {
            "server": SERVER_INFO,
            "mcpIdentity": MCP_IDENTITY,
            "readOnlyMode": READ_ONLY,
            "debugMode": DEBUG,
            "pythonExecutable": sys.executable,
            "pbiCliFound": pbi_path is not None,
            "pbiCliPath": pbi_path,
            "pbiCliVersion": None,
            "powerBIDesktopRunning": is_powerbi_desktop_running(),
        }
        if pbi_path:
            ok, out = run_pbi("--version", timeout=10)
            health["pbiCliVersion"] = out if ok else None
        return make_result(json.dumps(health, indent=2), False)

    # Connection
    if name == "pbi_connect":
        ca = ["connect"]
        if args.get("dataSource"):
            ca += ["--data-source", args["dataSource"]]
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_disconnect":
        ok, out = run_pbi("disconnect")
        return make_result(out, not ok)
    if name == "pbi_connections_list":
        ok, out = run_pbi("connections", "list")
        return make_result(out, not ok)

    # Model inspection
    if name == "pbi_model_stats":
        ok, out = run_pbi("model", "stats")
        return make_result(out, not ok)
    if name == "pbi_table_list":
        ok, out = run_pbi("table", "list")
        return make_result(out, not ok)
    if name == "pbi_column_list":
        ok, out = run_pbi("column", "list", "--table", args["table"])
        return make_result(out, not ok)
    if name == "pbi_measure_list":
        ok, out = run_pbi("measure", "list")
        return make_result(out, not ok)
    if name == "pbi_relationship_list":
        ok, out = run_pbi("relationship", "list")
        return make_result(out, not ok)
    if name == "pbi_security_role_list":
        ok, out = run_pbi("security-role", "list")
        return make_result(out, not ok)

    # Context tools
    if name == "pbi_workspace_context":
        ok, p = build_workspace_context()
        if not ok:
            degraded = build_degraded_context(p, args.get("projectPath"))
            return make_result(json.dumps(degraded, indent=2), False)
        return make_result(json.dumps(p, indent=2), False)
    if name == "pbi_model_health_snapshot":
        ok, p = build_workspace_context()
        if not ok:
            degraded = build_degraded_context(p, args.get("projectPath"))
            return make_result(json.dumps(degraded, indent=2), False)
        h = {
            "readOnlyMode": p.get("readOnlyMode", READ_ONLY),
            "summary": p.get("summary", {}),
            "qualitySignals": p.get("qualitySignals", {}),
            "recommendations": [],
        }
        s = h["qualitySignals"]
        if s.get("manyToManyRelationships", 0) > 0:
            h["recommendations"].append("Review many-to-many relationships.")
        if s.get("bidirectionalRelationships", 0) > 0:
            h["recommendations"].append("Review bidirectional filters.")
        if not s.get("rolesDefined", False):
            h["recommendations"].append("No roles found — validate RLS requirements.")
        return make_result(json.dumps(h, indent=2))
    if name == "pbi_relationship_risk_context":
        ok, p = build_workspace_context()
        if not ok:
            degraded = build_degraded_context(p, args.get("projectPath"))
            return make_result(json.dumps(degraded, indent=2), False)
        return make_result(json.dumps({
            "summary": p.get("qualitySignals", {}),
            "relationships": extract_items(p.get("sources", {}).get("relationships")),
        }, indent=2))
    if name == "pbi_measure_audit_context":
        ok, p = build_workspace_context()
        if not ok:
            degraded = build_degraded_context(p, args.get("projectPath"))
            return make_result(json.dumps(degraded, indent=2), False)
        return make_result(json.dumps({
            "summary": p.get("summary", {}),
            "measurePlacement": p.get("summary", {}).get("topMeasureTables", []),
            "rawMeasures": extract_items(p.get("sources", {}).get("measures")),
        }, indent=2))
    if name == "pbi_model_review":
        ok, p = build_workspace_context()
        if not ok:
            degraded = build_degraded_context(p, args.get("projectPath"))
            return make_result(json.dumps(degraded, indent=2), False)
        review = build_model_review_payload(p)
        return make_result(json.dumps(review, indent=2))
    if name == "pbi_connect_and_review":
        connection_attempts = []
        chosen_data_source = None

        preferred_data_source = args.get("dataSource")
        if preferred_data_source:
            ok_conn, conn_out = run_pbi("connect", "--data-source", preferred_data_source)
            connection_attempts.append({
                "mode": "explicit",
                "dataSource": preferred_data_source,
                "ok": ok_conn,
                "output": conn_out,
            })
            if ok_conn:
                chosen_data_source = preferred_data_source
        else:
            ok_conn, conn_out = run_pbi("connect")
            connection_attempts.append({
                "mode": "default",
                "dataSource": None,
                "ok": ok_conn,
                "output": conn_out,
            })

        if chosen_data_source is None and (not connection_attempts[-1]["ok"]):
            ok_list, payload, list_raw = run_pbi_json("connections", "list")
            if not ok_list:
                return make_result(
                    f"Unable to connect automatically. Last connect error: {connection_attempts[-1]['output']}. "
                    f"connections/list error: {list_raw}",
                    True,
                )

            candidates = extract_connection_candidates(payload)
            for candidate in candidates:
                ok_try, out_try = run_pbi("connect", "--data-source", candidate)
                connection_attempts.append({
                    "mode": "candidate",
                    "dataSource": candidate,
                    "ok": ok_try,
                    "output": out_try,
                })
                if ok_try:
                    chosen_data_source = candidate
                    break

            if chosen_data_source is None:
                return make_result(
                    "No active connection was established automatically. Open a PBIX in Power BI Desktop and retry. "
                    f"Attempts: {json.dumps(connection_attempts, ensure_ascii=False)}",
                    True,
                )

        ok_ctx, ctx = build_workspace_context()
        if not ok_ctx:
            degraded = {
                "connection": {
                    "autoConnectAttempted": True,
                    "selectedDataSource": chosen_data_source,
                    "attempts": connection_attempts,
                },
                "review": build_degraded_context(ctx, args.get("projectPath")),
            }
            return make_result(json.dumps(degraded, indent=2), False)

        review = build_model_review_payload(ctx)
        response = {
            "connection": {
                "autoConnectAttempted": True,
                "selectedDataSource": chosen_data_source,
                "attempts": connection_attempts,
            },
            "review": review,
        }
        return make_result(json.dumps(response, indent=2))

    if name == "pbi_project_design_inspect":
        inspected = inspect_pbip_project(args.get("projectPath"))
        return make_result(json.dumps(inspected, indent=2), not inspected.get("ok", False))

    # DAX
    if name == "pbi_dax_execute":
        ok, out = run_pbi("dax", "execute", args["query"], timeout=60)
        return make_result(out, not ok)
    if name == "pbi_dax_validate":
        ok, out = run_pbi("dax", "validate", args["expression"])
        return make_result(out, not ok)

    # Modification
    if name == "pbi_measure_create":
        ca = ["measure", "create", "--table", args["table"], "--name", args["name"], "--expression", args["expression"]]
        if args.get("formatString"):
            ca += ["--format-string", args["formatString"]]
        if args.get("displayFolder"):
            ca += ["--display-folder", args["displayFolder"]]
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_column_set":
        ok, out = run_pbi("column", "set", "--table", args["table"], "--column", args["column"], "--property", args["property"], "--value", args["value"])
        return make_result(out, not ok)
    if name == "pbi_relationship_create":
        ok, out = run_pbi("relationship", "create", "--from-table", args["fromTable"], "--from-column", args["fromColumn"], "--to-table", args["toTable"], "--to-column", args["toColumn"])
        return make_result(out, not ok)
    if name == "pbi_security_role_create":
        ca = ["security-role", "create", "--name", args["name"]]
        if args.get("filterExpression"):
            ca += ["--filter-expression", args["filterExpression"]]
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    # Deployment
    if name == "pbi_export_tmdl":
        ok, out = run_pbi("database", "export-tmdl", "--path", args.get("path", "./pbip/model"))
        return make_result(out, not ok)
    if name == "pbi_import_tmdl":
        ok, out = run_pbi("database", "import-tmdl", "--path", args["path"])
        return make_result(out, not ok)
    if name == "pbi_diff_tmdl":
        ok, out = run_pbi("database", "diff-tmdl", "--path", args["path"])
        return make_result(out, not ok)

    # Diagnostics
    if name == "pbi_trace_start":
        ok, out = run_pbi("trace", "start")
        return make_result(out, not ok)
    if name == "pbi_trace_fetch":
        ok, out = run_pbi("trace", "fetch")
        return make_result(out, not ok)
    if name == "pbi_trace_stop":
        ok, out = run_pbi("trace", "stop")
        return make_result(out, not ok)

    # ---------------------------------------------------------------------------
    # Report Layer (PBIR — no live model connection required)
    # ---------------------------------------------------------------------------
    if name == "pbi_report_info":
        ok, out = run_pbi("report", "info", *_report_args(args))
        return make_result(out, not ok)
    if name == "pbi_report_validate":
        ok, out = run_pbi("report", "validate", *_report_args(args))
        return make_result(out, not ok)
    if name == "pbi_report_create":
        ca = ["report", "create", "--name", args["name"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_report_reload":
        ok, out = run_pbi("report", "reload", *_report_args(args))
        return make_result(out, not ok)

    # Pages
    if name == "pbi_page_list":
        ok, out = run_pbi("report", "info", *_report_args(args))
        return make_result(out, not ok)
    if name == "pbi_page_add":
        ca = ["report", "add-page", "--name", args["name"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_page_delete":
        ca = ["report", "delete-page", "--page", args["page"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    # Visuals
    if name == "pbi_visual_list":
        ca = ["visual", "list", "--page", args["page"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_visual_add":
        ca = ["visual", "add", "--page", args["page"], "--type", args["type"]]
        if args.get("x") is not None: ca += ["--x", str(args["x"])]
        if args.get("y") is not None: ca += ["--y", str(args["y"])]
        if args.get("width") is not None: ca += ["--w", str(args["width"])]
        if args.get("height") is not None: ca += ["--h", str(args["height"])]
        ca += _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_visual_get":
        ca = ["visual", "get", "--page", args["page"], "--visual", args["visual"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_visual_bind":
        ca = ["visual", "bind", "--page", args["page"], "--visual", args["visual"],
              "--table", args["table"], "--column", args["column"]]
        if args.get("role"): ca += ["--role", args["role"]]
        ca += _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_visual_update":
        ca = ["visual", "update", "--page", args["page"], "--visual", args["visual"],
              "--property", args["property"], "--value", args["value"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_visual_delete":
        ca = ["visual", "delete", "--page", args["page"], "--visual", args["visual"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    # Filters
    if name == "pbi_filters_list":
        ca = ["filters", "list", "--page", args["page"]]
        if args.get("visual"): ca += ["--visual", args["visual"]]
        ca += _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_filters_add_categorical":
        ca = ["filters", "add-categorical", "--page", args["page"],
              "--table", args["table"], "--column", args["column"],
              "--values", args["values"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_filters_add_topn":
        ca = ["filters", "add-topn", "--page", args["page"],
              "--table", args["table"], "--column", args["column"],
              "--n", str(int(args["n"]))] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_filters_clear":
        ca = ["filters", "clear", "--page", args["page"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    # Bookmarks
    if name == "pbi_bookmarks_list":
        ok, out = run_pbi("bookmarks", "list", *_report_args(args))
        return make_result(out, not ok)
    if name == "pbi_bookmarks_add":
        ca = ["bookmarks", "add", "--name", args["name"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)
    if name == "pbi_bookmarks_delete":
        ca = ["bookmarks", "delete", "--name", args["name"]] + _report_args(args)
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    # ---------------------------------------------------------------------------
    # Extended Model Layer
    # ---------------------------------------------------------------------------
    if name == "pbi_partition_list":
        ok, out = run_pbi("partition", "list", "--table", args["table"])
        return make_result(out, not ok)
    if name == "pbi_hierarchy_list":
        ok, out = run_pbi("hierarchy", "list")
        return make_result(out, not ok)
    if name == "pbi_perspective_list":
        ok, out = run_pbi("perspective", "list")
        return make_result(out, not ok)
    if name == "pbi_dax_clear_cache":
        ok, out = run_pbi("dax", "clear-cache")
        return make_result(out, not ok)
    if name == "pbi_export_tmsl":
        ca = ["database", "export-tmsl"]
        if args.get("path"): ca += ["--path", args["path"]]
        ok, out = run_pbi(*ca)
        return make_result(out, not ok)

    return make_result(f"Unknown tool: {name}", is_error=True)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def handle_request(msg):
    method = msg.get("method")
    req_id = msg.get("id")

    # Notifications (no id) — just ignore
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-11-25"),
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        p = msg.get("params", {})
        return handle_tool_call(p.get("name", ""), p.get("arguments", {}))

    if method == "ping":
        return {}

    send_error(req_id, -32601, f"Unknown method: {method}")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _setup_logging()
    log(f"[START] pid={os.getpid()} python={sys.executable}")

    msg = None
    while True:
        try:
            msg = read_message()
            if msg is None:
                break  # EOF — VS Code closed the pipe

            log(f"[RECV] method={msg.get('method')} id={msg.get('id')}")

            result = handle_request(msg)
            if result is not None:
                send_result(msg["id"], result)
                log(f"[SENT] id={msg['id']}")

        except Exception as e:
            log(f"[ERROR] {e}")
            try:
                if msg and msg.get("id") is not None:
                    send_error(msg["id"], -32603, str(e))
            except Exception:
                pass


if __name__ == "__main__":
    main()
