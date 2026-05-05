"""
Power BI MCP Server (v2)

A local MCP server that wraps pbi-cli for Power BI Desktop operations.
Transport: stdio JSON-RPC with Content-Length framing.
"""

import json
import os
import subprocess
import sys
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

READ_ONLY = os.getenv("PBI_MCP_READ_ONLY", "true").lower() in ("1", "true", "yes")
DEBUG = os.getenv("PBI_MCP_DEBUG_LOG", "").lower() in ("1", "true", "yes")

MUTATING_TOOLS = {
    "pbi_measure_create",
    "pbi_column_set",
    "pbi_relationship_create",
    "pbi_security_role_create",
    "pbi_import_tmdl",
}

SERVER_INFO = {"name": "powerbi-mcp-server", "version": "2.0.0"}
CAPABILITIES = {"tools": {}}

# ---------------------------------------------------------------------------
# Logging (stderr, opt-in file redirect)
# ---------------------------------------------------------------------------

_log_file = None

def _setup_logging():
    global _log_file
    if not DEBUG:
        # Suppress all stderr output so VS Code doesn't confuse it with protocol data
        devnull = open(os.devnull, "w")
        sys.stderr = devnull
        return
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server.log")
    try:
        _log_file = open(log_path, "a", encoding="utf-8")
        sys.stderr = _log_file
    except OSError:
        pass

def log(msg):
    if DEBUG:
        print(msg, file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# MCP Transport: Content-Length framed JSON-RPC over stdio
# ---------------------------------------------------------------------------
# VS Code MCP host sends:
#   Content-Length: <n>\r\n
#   \r\n
#   <json body of exactly n bytes>
#
# We MUST reply in the same format.
# Key: use sys.stdin.buffer (binary) to avoid encoding/newline issues on Windows.

def read_message():
    """Read one Content-Length framed JSON-RPC message from stdin (binary)."""
    # Read headers until we get an empty line
    headers = {}
    while True:
        raw_line = sys.stdin.buffer.readline()
        if not raw_line:
            return None  # EOF
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if headers:
                break  # End of headers
            else:
                continue  # Skip leading blank lines (VS Code sometimes sends these)
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()
        elif line.startswith("{"):
            # Fallback: newline-delimited JSON (no headers)
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None

    body = b""
    while len(body) < length:
        chunk = sys.stdin.buffer.read(length - len(body))
        if not chunk:
            return None  # EOF mid-read
        body += chunk

    return json.loads(body.decode("utf-8", errors="replace"))


def write_message(obj):
    """Write one Content-Length framed JSON-RPC message to stdout (binary)."""
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    sys.stdout.buffer.write(header)
    sys.stdout.buffer.write(body)
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
    cmd = ["pbi", "--json"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=(os.name == "nt"))
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


def make_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {"name": "pbi_connect", "description": "Connect to a running Power BI Desktop instance.", "inputSchema": {"type": "object", "properties": {"dataSource": {"type": "string", "description": "Optional localhost:port."}}}},
    {"name": "pbi_disconnect", "description": "Disconnect from Power BI Desktop.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_connections_list", "description": "List available Power BI Desktop connections.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_model_stats", "description": "Get model statistics.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_table_list", "description": "List all tables in the semantic model.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_column_list", "description": "List columns in a table.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string", "description": "Table name."}}, "required": ["table"]}},
    {"name": "pbi_measure_list", "description": "List all measures with DAX expressions.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_relationship_list", "description": "List all relationships.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_security_role_list", "description": "List security roles (RLS/OLS).", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_workspace_context", "description": "Full model snapshot: stats, tables, measures, relationships, roles.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_model_health_snapshot", "description": "Health summary with quality signals.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_relationship_risk_context", "description": "Relationship risk analysis.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_measure_audit_context", "description": "Measure placement audit.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_dax_execute", "description": "Execute a DAX query.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "DAX query."}}, "required": ["query"]}},
    {"name": "pbi_dax_validate", "description": "Validate a DAX expression.", "inputSchema": {"type": "object", "properties": {"expression": {"type": "string", "description": "DAX expression."}}, "required": ["expression"]}},
    {"name": "pbi_measure_create", "description": "Create a DAX measure.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string"}, "name": {"type": "string"}, "expression": {"type": "string"}, "formatString": {"type": "string"}, "displayFolder": {"type": "string"}}, "required": ["table", "name", "expression"]}},
    {"name": "pbi_column_set", "description": "Set a column property.", "inputSchema": {"type": "object", "properties": {"table": {"type": "string"}, "column": {"type": "string"}, "property": {"type": "string"}, "value": {"type": "string"}}, "required": ["table", "column", "property", "value"]}},
    {"name": "pbi_relationship_create", "description": "Create a relationship.", "inputSchema": {"type": "object", "properties": {"fromTable": {"type": "string"}, "fromColumn": {"type": "string"}, "toTable": {"type": "string"}, "toColumn": {"type": "string"}}, "required": ["fromTable", "fromColumn", "toTable", "toColumn"]}},
    {"name": "pbi_security_role_create", "description": "Create a security role.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "filterExpression": {"type": "string"}}, "required": ["name"]}},
    {"name": "pbi_export_tmdl", "description": "Export model as TMDL.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Output directory."}}}},
    {"name": "pbi_import_tmdl", "description": "Import TMDL into model.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "pbi_diff_tmdl", "description": "Diff live model vs TMDL on disk.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "pbi_trace_start", "description": "Start diagnostic trace.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_trace_fetch", "description": "Fetch trace events.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pbi_trace_stop", "description": "Stop diagnostic trace.", "inputSchema": {"type": "object", "properties": {}}},
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def handle_tool_call(name, args):
    args = args or {}
    if READ_ONLY and name in MUTATING_TOOLS:
        return make_result("Blocked: read-only mode (PBI_MCP_READ_ONLY=true).", is_error=True)

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
        return make_result(json.dumps(p, indent=2), not ok)
    if name == "pbi_model_health_snapshot":
        ok, p = build_workspace_context()
        if not ok:
            return make_result(p, True)
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
            return make_result(p, True)
        return make_result(json.dumps({
            "summary": p.get("qualitySignals", {}),
            "relationships": extract_items(p.get("sources", {}).get("relationships")),
        }, indent=2))
    if name == "pbi_measure_audit_context":
        ok, p = build_workspace_context()
        if not ok:
            return make_result(p, True)
        return make_result(json.dumps({
            "summary": p.get("summary", {}),
            "measurePlacement": p.get("summary", {}).get("topMeasureTables", []),
            "rawMeasures": extract_items(p.get("sources", {}).get("measures")),
        }, indent=2))

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
            "protocolVersion": "2024-11-05",
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
