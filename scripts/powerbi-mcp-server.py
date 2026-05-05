"""
Power BI MCP Server

A Model Context Protocol (MCP) server that wraps pbi-cli commands,
exposing Power BI Desktop operations as MCP tools for GitHub Copilot.

Transport: stdio with Content-Length framing (LSP-style).
Backend: shells out to `pbi --json <command>` for all operations.

Requires: Python 3.10+, pbi-cli installed and on PATH.
"""

import json
import subprocess
import sys
import os

READ_ONLY = os.getenv("PBI_MCP_READ_ONLY", "true").lower() in ("1", "true", "yes")
MUTATING_TOOLS = {
    "pbi_measure_create",
    "pbi_column_set",
    "pbi_relationship_create",
    "pbi_security_role_create",
    "pbi_import_tmdl",
}

# ---------------------------------------------------------------------------
# MCP Protocol Transport (Content-Length framed JSON-RPC over stdio)
# ---------------------------------------------------------------------------

def read_message():
    """
    Read a JSON-RPC message from stdin.

    Supports both:
    1) Content-Length framed transport (LSP-style)
    2) Newline-delimited JSON transport
    """
    first_line = sys.stdin.buffer.readline()
    if not first_line:
        return None

    first_line_str = first_line.decode("utf-8", errors="replace").rstrip("\r\n")
    if first_line_str == "":
        return None

    # Mode 1: Content-Length framing
    if ":" in first_line_str and first_line_str.lower().startswith("content-length"):
        headers = {}

        key, value = first_line_str.split(":", 1)
        headers[key.strip().lower()] = value.strip()

        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line_str == "":
                break
            if ":" in line_str:
                h_key, h_value = line_str.split(":", 1)
                headers[h_key.strip().lower()] = h_value.strip()

        content_length_raw = headers.get("content-length", "0")
        try:
            content_length = int(content_length_raw)
        except ValueError:
            return None

        if content_length <= 0:
            return None

        body = sys.stdin.buffer.read(content_length)
        if not body:
            return None
        return json.loads(body.decode("utf-8", errors="replace"))

    # Mode 2: Newline-delimited JSON
    # Some MCP hosts send plain JSON objects per line.
    if first_line_str.startswith("{"):
        return json.loads(first_line_str)

    return None


def send_message(msg):
    """Send a Content-Length framed JSON-RPC message to stdout."""
    body = json.dumps(msg)
    encoded = body.encode("utf-8")
    header = f"Content-Length: {len(encoded)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode("utf-8"))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def send_result(req_id, result):
    send_message({"jsonrpc": "2.0", "id": req_id, "result": result})


def send_error(req_id, code, message):
    send_message({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message}
    })


# ---------------------------------------------------------------------------
# pbi-cli Execution
# ---------------------------------------------------------------------------

def run_pbi(*args, timeout=30):
    """Run a pbi-cli command and return (success, output_text)."""
    cmd = ["pbi", "--json"] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=(os.name == "nt")
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip() or output or f"pbi-cli exited with code {result.returncode}"
            return False, err
        return True, output
    except FileNotFoundError:
        return False, "pbi-cli not found on PATH. Install with: pipx install pbi-cli-tool"
    except subprocess.TimeoutExpired:
        return False, f"pbi-cli command timed out after {timeout}s"
    except Exception as e:
        return False, f"Error running pbi-cli: {str(e)}"


def run_pbi_json(*args, timeout=30):
    """Run pbi-cli and try to parse JSON output."""
    ok, out = run_pbi(*args, timeout=timeout)
    if not ok:
        return False, None, out
    try:
        return True, json.loads(out), out
    except json.JSONDecodeError:
        return True, None, out


def extract_items(payload):
    """Extract list-like items from common JSON response shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in (
            "items", "data", "results", "tables", "columns", "measures", "relationships", "roles"
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def build_workspace_context():
    """Build high-context snapshot from model stats, tables, measures, relationships, and roles."""
    commands = {
        "modelStats": ("model", "stats"),
        "tables": ("table", "list"),
        "measures": ("measure", "list"),
        "relationships": ("relationship", "list"),
        "roles": ("security-role", "list"),
    }
    context = {
        "readOnlyMode": READ_ONLY,
        "sources": {},
        "summary": {},
        "qualitySignals": {},
    }

    for label, cmd in commands.items():
        ok, payload, raw = run_pbi_json(*cmd)
        if not ok:
            return False, f"Failed to fetch {label}: {raw}"
        context["sources"][label] = payload if payload is not None else {"raw": raw}

    tables = extract_items(context["sources"].get("tables"))
    measures = extract_items(context["sources"].get("measures"))
    relationships = extract_items(context["sources"].get("relationships"))
    roles = extract_items(context["sources"].get("roles"))

    # Measure placement by table
    measure_counts = {}
    for measure in measures:
        table_name = (
            measure.get("table")
            or measure.get("tableName")
            or measure.get("table_name")
            or "Unknown"
        )
        measure_counts[table_name] = measure_counts.get(table_name, 0) + 1

    many_to_many = 0
    bidirectional = 0
    inactive = 0
    for rel in relationships:
        cardinality = str(rel.get("cardinality") or rel.get("relationshipCardinality") or "").lower()
        direction = str(rel.get("direction") or rel.get("crossFilteringBehavior") or "").lower()
        is_active = rel.get("isActive")
        if "many" in cardinality and ("many-to-many" in cardinality or "m:m" in cardinality):
            many_to_many += 1
        if "both" in direction or "bi" in direction:
            bidirectional += 1
        if is_active is not None and not _to_bool(is_active, default=True):
            inactive += 1

    context["summary"] = {
        "tableCount": len(tables),
        "measureCount": len(measures),
        "relationshipCount": len(relationships),
        "roleCount": len(roles),
        "topMeasureTables": sorted(
            [{"table": k, "measureCount": v} for k, v in measure_counts.items()],
            key=lambda x: x["measureCount"],
            reverse=True,
        )[:10],
    }

    context["qualitySignals"] = {
        "manyToManyRelationships": many_to_many,
        "bidirectionalRelationships": bidirectional,
        "inactiveRelationships": inactive,
        "rolesDefined": len(roles) > 0,
    }

    return True, context


def make_tool_result(text, is_error=False):
    """Format a tool call result for MCP."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error
    }


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

TOOLS = [
    # Connection
    {
        "name": "pbi_connect",
        "description": "Connect to a running Power BI Desktop instance. Must be called before any model operations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataSource": {
                    "type": "string",
                    "description": "Optional data source (e.g., localhost:port). If omitted, auto-discovers."
                }
            }
        }
    },
    {
        "name": "pbi_disconnect",
        "description": "Disconnect from Power BI Desktop.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_connections_list",
        "description": "List available Power BI Desktop connections.",
        "inputSchema": {"type": "object", "properties": {}}
    },

    # Model inspection
    {
        "name": "pbi_model_stats",
        "description": "Get model statistics: table count, column count, measure count, relationship count, model size.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_table_list",
        "description": "List all tables in the semantic model with their types and row counts.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_column_list",
        "description": "List all columns in a specific table with data types, visibility, and properties.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Table name to list columns for."
                }
            },
            "required": ["table"]
        }
    },
    {
        "name": "pbi_measure_list",
        "description": "List all measures in the model with their table placement, DAX expressions, and display folders.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_relationship_list",
        "description": "List all relationships with from/to tables, columns, cardinality, cross-filter direction, and active status.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_security_role_list",
        "description": "List all security roles (RLS/OLS) defined in the model.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_workspace_context",
        "description": "Return a high-context model snapshot combining stats, tables, measures, relationships, and security roles.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_model_health_snapshot",
        "description": "Return a concise health summary with key quality signals: many-to-many, bidirectional, inactive relationships, and role coverage.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_relationship_risk_context",
        "description": "Return relationship-focused risk context, including many-to-many, bidirectional, and inactive relationships with raw relationship data.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_measure_audit_context",
        "description": "Return measure placement context by table to help detect scattered measures and model hygiene issues.",
        "inputSchema": {"type": "object", "properties": {}}
    },

    # DAX
    {
        "name": "pbi_dax_execute",
        "description": "Execute a DAX query against the connected model. Use EVALUATE for table queries, or wrap in EVALUATE ROW() for scalar expressions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "DAX query to execute (e.g., 'EVALUATE TOPN(10, Sales)')."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "pbi_dax_validate",
        "description": "Validate a DAX expression without executing it. Returns syntax errors if any.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "DAX expression to validate."
                }
            },
            "required": ["expression"]
        }
    },

    # Model modification
    {
        "name": "pbi_measure_create",
        "description": "Create a new DAX measure in the model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Table to create the measure in (use dedicated measures table)."
                },
                "name": {
                    "type": "string",
                    "description": "Measure name."
                },
                "expression": {
                    "type": "string",
                    "description": "DAX expression for the measure."
                },
                "formatString": {
                    "type": "string",
                    "description": "Optional format string (e.g., '$#,##0.00', '0.0%')."
                },
                "displayFolder": {
                    "type": "string",
                    "description": "Optional display folder for organizing measures."
                }
            },
            "required": ["table", "name", "expression"]
        }
    },
    {
        "name": "pbi_column_set",
        "description": "Set a property on a column (e.g., IsHidden, Description, DisplayFolder).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table name."},
                "column": {"type": "string", "description": "Column name."},
                "property": {"type": "string", "description": "Property to set (e.g., IsHidden, Description)."},
                "value": {"type": "string", "description": "Value to set."}
            },
            "required": ["table", "column", "property", "value"]
        }
    },
    {
        "name": "pbi_relationship_create",
        "description": "Create a new relationship between two tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fromTable": {"type": "string", "description": "Many-side table."},
                "fromColumn": {"type": "string", "description": "Many-side column."},
                "toTable": {"type": "string", "description": "One-side (lookup) table."},
                "toColumn": {"type": "string", "description": "One-side column."}
            },
            "required": ["fromTable", "fromColumn", "toTable", "toColumn"]
        }
    },
    {
        "name": "pbi_security_role_create",
        "description": "Create a new security role with an optional DAX filter expression.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Role name."},
                "filterExpression": {"type": "string", "description": "Optional DAX filter expression for RLS."}
            },
            "required": ["name"]
        }
    },

    # Deployment
    {
        "name": "pbi_export_tmdl",
        "description": "Export the current model as TMDL files for source control.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Output directory for TMDL files (default: ./pbip/model)."
                }
            }
        }
    },
    {
        "name": "pbi_import_tmdl",
        "description": "Import TMDL files into the connected model (replaces current model state).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing TMDL files."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "pbi_diff_tmdl",
        "description": "Show differences between the live model and TMDL files on disk.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing TMDL files to diff against."
                }
            },
            "required": ["path"]
        }
    },

    # Diagnostics
    {
        "name": "pbi_trace_start",
        "description": "Start a diagnostic trace to capture query events from Power BI Desktop.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_trace_fetch",
        "description": "Fetch trace events captured since the last trace start.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pbi_trace_stop",
        "description": "Stop the diagnostic trace.",
        "inputSchema": {"type": "object", "properties": {}}
    },
]

# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

def handle_tool_call(name, arguments):
    """Execute a tool call and return the MCP result."""
    args = arguments or {}

    if READ_ONLY and name in MUTATING_TOOLS:
        return make_tool_result(
            "Read-only mode is enabled (PBI_MCP_READ_ONLY=true). This mutating tool is blocked.",
            is_error=True,
        )

    # Connection
    if name == "pbi_connect":
        cli_args = ["connect"]
        if args.get("dataSource"):
            cli_args += ["--data-source", args["dataSource"]]
        ok, out = run_pbi(*cli_args)
        return make_tool_result(out, not ok)

    if name == "pbi_disconnect":
        ok, out = run_pbi("disconnect")
        return make_tool_result(out, not ok)

    if name == "pbi_connections_list":
        ok, out = run_pbi("connections", "list")
        return make_tool_result(out, not ok)

    # Model inspection
    if name == "pbi_model_stats":
        ok, out = run_pbi("model", "stats")
        return make_tool_result(out, not ok)

    if name == "pbi_table_list":
        ok, out = run_pbi("table", "list")
        return make_tool_result(out, not ok)

    if name == "pbi_column_list":
        ok, out = run_pbi("column", "list", "--table", args["table"])
        return make_tool_result(out, not ok)

    if name == "pbi_measure_list":
        ok, out = run_pbi("measure", "list")
        return make_tool_result(out, not ok)

    if name == "pbi_relationship_list":
        ok, out = run_pbi("relationship", "list")
        return make_tool_result(out, not ok)

    if name == "pbi_security_role_list":
        ok, out = run_pbi("security-role", "list")
        return make_tool_result(out, not ok)

    if name == "pbi_workspace_context":
        ok, payload = build_workspace_context()
        return make_tool_result(json.dumps(payload, indent=2), not ok)

    if name == "pbi_model_health_snapshot":
        ok, payload = build_workspace_context()
        if not ok:
            return make_tool_result(payload, is_error=True)
        health = {
            "readOnlyMode": payload.get("readOnlyMode", READ_ONLY),
            "summary": payload.get("summary", {}),
            "qualitySignals": payload.get("qualitySignals", {}),
            "recommendations": [],
        }
        signals = health["qualitySignals"]
        if signals.get("manyToManyRelationships", 0) > 0:
            health["recommendations"].append("Review many-to-many relationships and validate aggregation behavior.")
        if signals.get("bidirectionalRelationships", 0) > 0:
            health["recommendations"].append("Review bidirectional filters; keep one-direction unless explicitly required.")
        if not signals.get("rolesDefined", False):
            health["recommendations"].append("No roles found. Validate whether RLS is required for this model.")
        return make_tool_result(json.dumps(health, indent=2))

    if name == "pbi_relationship_risk_context":
        ok, payload = build_workspace_context()
        if not ok:
            return make_tool_result(payload, is_error=True)
        relationships = extract_items(payload.get("sources", {}).get("relationships"))
        report = {
            "summary": payload.get("qualitySignals", {}),
            "relationships": relationships,
        }
        return make_tool_result(json.dumps(report, indent=2))

    if name == "pbi_measure_audit_context":
        ok, payload = build_workspace_context()
        if not ok:
            return make_tool_result(payload, is_error=True)
        report = {
            "summary": payload.get("summary", {}),
            "measurePlacement": payload.get("summary", {}).get("topMeasureTables", []),
            "rawMeasures": extract_items(payload.get("sources", {}).get("measures")),
        }
        return make_tool_result(json.dumps(report, indent=2))

    # DAX
    if name == "pbi_dax_execute":
        ok, out = run_pbi("dax", "execute", args["query"], timeout=60)
        return make_tool_result(out, not ok)

    if name == "pbi_dax_validate":
        ok, out = run_pbi("dax", "validate", args["expression"])
        return make_tool_result(out, not ok)

    # Model modification
    if name == "pbi_measure_create":
        cli_args = ["measure", "create",
                     "--table", args["table"],
                     "--name", args["name"],
                     "--expression", args["expression"]]
        if args.get("formatString"):
            cli_args += ["--format-string", args["formatString"]]
        if args.get("displayFolder"):
            cli_args += ["--display-folder", args["displayFolder"]]
        ok, out = run_pbi(*cli_args)
        return make_tool_result(out, not ok)

    if name == "pbi_column_set":
        ok, out = run_pbi("column", "set",
                          "--table", args["table"],
                          "--column", args["column"],
                          "--property", args["property"],
                          "--value", args["value"])
        return make_tool_result(out, not ok)

    if name == "pbi_relationship_create":
        ok, out = run_pbi("relationship", "create",
                          "--from-table", args["fromTable"],
                          "--from-column", args["fromColumn"],
                          "--to-table", args["toTable"],
                          "--to-column", args["toColumn"])
        return make_tool_result(out, not ok)

    if name == "pbi_security_role_create":
        cli_args = ["security-role", "create", "--name", args["name"]]
        if args.get("filterExpression"):
            cli_args += ["--filter-expression", args["filterExpression"]]
        ok, out = run_pbi(*cli_args)
        return make_tool_result(out, not ok)

    # Deployment
    if name == "pbi_export_tmdl":
        path = args.get("path", "./pbip/model")
        ok, out = run_pbi("database", "export-tmdl", "--path", path)
        return make_tool_result(out, not ok)

    if name == "pbi_import_tmdl":
        ok, out = run_pbi("database", "import-tmdl", "--path", args["path"])
        return make_tool_result(out, not ok)

    if name == "pbi_diff_tmdl":
        ok, out = run_pbi("database", "diff-tmdl", "--path", args["path"])
        return make_tool_result(out, not ok)

    # Diagnostics
    if name == "pbi_trace_start":
        ok, out = run_pbi("trace", "start")
        return make_tool_result(out, not ok)

    if name == "pbi_trace_fetch":
        ok, out = run_pbi("trace", "fetch")
        return make_tool_result(out, not ok)

    if name == "pbi_trace_stop":
        ok, out = run_pbi("trace", "stop")
        return make_tool_result(out, not ok)

    return make_tool_result(f"Unknown tool: {name}", is_error=True)


# ---------------------------------------------------------------------------
# MCP Protocol Handlers
# ---------------------------------------------------------------------------

SERVER_INFO = {
    "name": "powerbi-mcp-server",
    "version": "1.1.0"
}

CAPABILITIES = {
    "tools": {}
}


def handle_request(msg):
    """Handle a JSON-RPC request and return a response."""
    method = msg.get("method")
    req_id = msg.get("id")

    # Notification (no id) - acknowledge silently
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO
        }

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        return handle_tool_call(tool_name, tool_args)

    if method == "ping":
        return {}

    # Unknown method
    send_error(req_id, -32601, f"Method not found: {method}")
    return None


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def main():
    """MCP server main loop - reads JSON-RPC messages from stdin, responds on stdout."""
    debug = os.getenv("PBI_MCP_DEBUG_LOG", "").lower() in ("1", "true", "yes")
    log_file = None

    # Redirect stderr to file only when debug logging is enabled.
    if debug:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp-server.log")
        try:
            log_file = open(log_path, "a", encoding="utf-8")
            sys.stderr = log_file
        except OSError:
            pass

    if debug:
        print(f"[START] powerbi-mcp-server starting (pid={os.getpid()})", file=sys.stderr, flush=True)

    consecutive_empty = 0
    msg = None
    while True:
        try:
            msg = read_message()

            # None means EOF (stdin closed) — exit cleanly.
            if msg is None:
                # Allow a few empty reads before exiting, in case of startup race.
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0

            if debug:
                print(f"[RECV] method={msg.get('method')} id={msg.get('id')}", file=sys.stderr, flush=True)

            result = handle_request(msg)
            if result is not None:
                send_result(msg["id"], result)
                if debug:
                    print(f"[SENT] id={msg.get('id')} method={msg.get('method')}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr, flush=True)
            try:
                if msg and msg.get("id") is not None:
                    send_error(msg["id"], -32603, str(e))
            except Exception:
                pass


if __name__ == "__main__":
    main()
