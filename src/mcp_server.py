#!/usr/bin/env python3
"""Precedent MCP server — exposes the harness to any MCP client (Claude Code, Codex, Cursor).

Stdlib only, stdio transport (newline-delimited JSON-RPC 2.0). No install.

Tools:
  retrieve_precedent(situation) -> the org's recorded decisions that apply
  record_precedent(note)        -> structure + store a decision as 'unconfirmed'
  govern(files, action?)        -> autonomy verdict: act_silently/act_and_flag/require_review/escalate/deny

Register in Claude Code (project scope) via .mcp.json, or:
  claude mcp add precedent -- python3 tools/mcp_server.py
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precedent, govern_cli

PROTOCOL_DEFAULT = "2025-06-18"
SERVER_INFO = {"name": "precedent", "version": "0.1.0"}

TOOLS = [
    {"name": "retrieve_precedent",
     "description": ("Consult the org's recorded decisions BEFORE any non-trivial choice "
                     "(library, data store, touching payments/checkout/catalog/auth, adding an "
                     "endpoint, a migration). Returns applicable decisions, their authority "
                     "(guardrail overrides your judgment), why they apply, a recommendation, and "
                     "an escalate-if condition."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"situation": {"type": "string",
                        "description": "One line: what you're deciding + files involved."}},
                     "required": ["situation"]}},
    {"name": "record_precedent",
     "description": ("Record a decision AFTER you make it, or a constraint you discovered that "
                     "the code doesn't state. One free-text line; auto-structured and stored as "
                     "'unconfirmed' until a human promotes it. Record liberally."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"note": {"type": "string",
                        "description": "Free text: situation; decided X; because Y; scope paths."}},
                     "required": ["note"]}},
    {"name": "govern",
     "description": ("Get the autonomy verdict for a concrete action/PR BEFORE you merge/deploy. "
                     "Given changed files, a short title of the change, and the action, returns "
                     "act_silently / act_and_flag / require_review / escalate / deny. It retrieves "
                     "the org's applicable precedents, judges whether the change complies with or "
                     "CONFLICTS with them, and combines that with the action's risk. A guardrail "
                     "conflict is denied; irreversible actions (prod/money/deletes/migration) are "
                     "gated even under settled policy. If the verdict is not act_*, do NOT proceed — "
                     "record the reason and let a human decide."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"files": {"type": "array", "items": {"type": "string"},
                                              "description": "Changed file paths."},
                                    "title": {"type": "string",
                                              "description": "One line describing the change (what + why)."},
                                    "diff": {"type": "string",
                                              "description": "The ACTUAL code change (diff/patch or the new "
                                              "code). Strongly recommended — govern judges match/conflict on "
                                              "the real code, not just the title (a title can't reveal whether "
                                              "a new endpoint applies mandated audit logging)."},
                                    "action": {"type": "string",
                                              "description": "edit_file | merge | deploy | db_migration | ..."}},
                     "required": ["files"]}},
    {"name": "deprecate_precedent",
     "description": ("PROPOSE retiring a recorded decision that is now wrong, outdated, or replaced by a "
                     "newer one. You cannot retract unilaterally — this files a proposal; the decision "
                     "stays active (still enforced) until a human confirms. Use when a decision "
                     "contradicts current reality or a newer decision supersedes it."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"id": {"type": "string", "description": "Decision id to retire (e.g. E2, C-003)."},
                                    "reason": {"type": "string", "description": "Why it should be retired."},
                                    "superseded_by": {"type": "string", "description": "Optional id of the replacement."}},
                     "required": ["id", "reason"]}},
]

def _tool(name, args):
    if name == "retrieve_precedent":
        q = args["situation"]
        return precedent.format_packet(q, precedent.retrieve_packet(q))
    if name == "record_precedent":
        ep = precedent.record_episode(args["note"])
        return (f"recorded {ep['id']} (authority: unconfirmed — a human must promote it)\n"
                + json.dumps(ep, indent=2))
    if name == "deprecate_precedent":
        precedent.deprecate(args["id"], reason=args.get("reason", ""),
                            superseded_by=args.get("superseded_by"), propose=True, actor="agent")
        return (f"deprecation of {args['id']} PROPOSED (reason: {args.get('reason','')}). It stays active "
                "and enforced until a human confirms — you cannot retract a decision unilaterally.")
    if name == "govern":
        v = govern_cli.govern_diff(args["files"], args.get("title", ""), args.get("action"),
                                   diff=args.get("diff", ""))
        govern_cli.log_verdict(v)
        out = (f"verdict: {v['verdict']}\nauthority: {v['authority_state']}"
               f"  risk: {v['risk_tier']}  consequential: {v['consequential']}\n"
               f"governing precedent(s): {v['precedent_ids'] or '-'}\n"
               f"why: {v['why']}\n"
               f"→ {'ALLOW autonomously' if v['allow'] else 'HOLD — human review/approval required'}")
        if not v["allow"]:
            out += ("\n\nACTION REQUIRED: do not proceed. Get the required authority, then call "
                    "record_precedent with the decision + reason so the next agent inherits it. "
                    "(A no-precedent consequential change lands here — it is a NEW team decision.)")
        elif v["authority_state"] == "none":
            out += ("\n\nNote: no precedent governed this. If it establishes a pattern others should "
                    "follow (a reuse/canonical-source choice, a new convention), call record_precedent "
                    "so it is not re-litigated next time.")
        return out
    raise ValueError(f"unknown tool: {name}")

def _send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def _result(id_, result):
    _send({"jsonrpc": "2.0", "id": id_, "result": result})

def _error(id_, code, message):
    _send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})

def handle(msg):
    method, id_ = msg.get("method"), msg.get("id")
    if method == "initialize":
        proto = (msg.get("params") or {}).get("protocolVersion", PROTOCOL_DEFAULT)
        _result(id_, {"protocolVersion": proto,
                      "capabilities": {"tools": {}},
                      "serverInfo": SERVER_INFO})
    elif method == "notifications/initialized":
        pass  # notification, no reply
    elif method == "tools/list":
        _result(id_, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            text = _tool(params.get("name"), params.get("arguments") or {})
            _result(id_, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:
            _result(id_, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    elif method == "ping":
        _result(id_, {})
    elif id_ is not None:
        _error(id_, -32601, f"method not found: {method}")

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        handle(msg)

if __name__ == "__main__":
    main()
