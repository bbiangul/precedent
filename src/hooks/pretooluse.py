#!/usr/bin/env python3
"""PreToolUse hook — the in-loop tripwire that makes consulting precedents NON-OPTIONAL.

Fires before Write/Edit/MultiEdit/Bash. Fast + cheap by design: DETERMINISTIC scope match +
local keyword retrieval only — ZERO model calls, no token burn. Most actions (untouched scope)
exit silently in microseconds. When the change touches a scope that has recorded decisions, it
INJECTS them into the agent's context (additionalContext) so the agent cannot proceed without the
decision in view. It does NOT block — enforcement stays at the merge gate; the hook guarantees
CONSUMPTION (and logs touched scopes so the Stop hook can nudge recording).

Contract: reads a PreToolUse JSON on stdin; on a hit prints
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"..."}} and exits 0.
On no hit, exits 0 silently. Never blocks (no exit 2) — consumption, not enforcement.
"""
import json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import govern, precedent  # light: load decisions.json + risk-policy.json

RISKY_CMD = re.compile(r"\b(migrat|deploy|drop\s+table|rm\s+-rf|prod|credential|secret|terraform apply)\b", re.I)
SESSION_LOG = os.path.join(govern.REPO, ".precedent", "session_touch.jsonl")   # for the Stop hook


def paths_of(tool, ti):
    if tool in ("Write", "Edit"):
        return [ti["file_path"]] if ti.get("file_path") else []
    if tool == "MultiEdit":
        ps = [e.get("file_path") for e in ti.get("edits", []) if e.get("file_path")]
        return ps or ([ti["file_path"]] if ti.get("file_path") else [])
    return []


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    paths = paths_of(tool, ti)
    cmd = ti.get("command", "") if tool == "Bash" else ""

    # relativize paths to the repo so scope globs match
    rel = []
    for p in paths:
        rel.append(os.path.relpath(p, govern.REPO) if os.path.isabs(p) else p)

    ids = govern.in_scope(rel) if rel else []
    store = {p["id"]: p for p in precedent._all_precedents()}
    inscope = [store[i] for i in ids if i in store]
    risky = bool(RISKY_CMD.search(cmd))

    if not inscope and not risky:
        sys.exit(0)                                   # silent, instant — the common case

    # log the touch so the Stop hook can nudge recording (novel/guarded scopes)
    try:
        with open(SESSION_LOG, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "paths": rel, "cmd": cmd[:120],
                                "in_scope": [p["id"] for p in inscope]}) + "\n")
    except Exception:
        pass

    lines = []
    guard = [p for p in inscope if p["authority"] == "guardrail"]
    if inscope:
        lines.append("🔐 Precedent — recorded decisions govern the scope you're editing. Consult before proceeding:")
        for p in sorted(inscope, key=lambda p: {"guardrail": 0, "policy": 1}.get(p["authority"], 2)):
            lines.append(f"  • {p['id']} [{p['authority']}] {p['decision']}")
        if guard:
            lines.append("A guardrail applies: if your change conflicts with it, DO NOT proceed — "
                         "it will be blocked at the merge gate. If compliant, continue.")
    if risky and not inscope:
        lines.append("⚠ Precedent — this is a high-risk action (migration/deploy/prod/credential) with no "
                     "recorded decision. Treat it as a NEW consequential decision: consider `govern` first, "
                     "and record the rationale.")
    lines.append('If you are making a NEW decision here, record it: '
                 'python3 tools/precedent.py record "situation; decided X; because Y; scope <paths>"')

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": "\n".join(lines)}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
