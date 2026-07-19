#!/usr/bin/env python3
"""Stop hook — end-of-session nudge to RECORD decisions made in new/guarded territory.

The PreToolUse hook logs each touch of a governed or risky scope to session_touch.jsonl.
At session end this checks whether the agent worked in territory with NO existing precedent
(a novel/consequential decision it should record) and, if so, blocks the stop once to inject a
record nudge. Deterministic, no model calls. Respects stop_hook_active to avoid loops.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import govern

SESSION_LOG = os.path.join(govern.REPO, ".precedent", "session_touch.jsonl")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("stop_hook_active"):
        sys.exit(0)                                   # already nudged this turn — don't loop
    if not os.path.exists(SESSION_LOG):
        sys.exit(0)
    touches = [json.loads(l) for l in open(SESSION_LOG) if l.strip()]
    # novel territory = touched a governed/risky scope but NO precedent covered it -> should be recorded
    novel = [t for t in touches if not t.get("in_scope")]
    os.remove(SESSION_LOG)                             # reset for the next session
    if not novel:
        sys.exit(0)
    scopes = sorted({p for t in novel for p in t.get("paths", []) if p})[:6]
    msg = ("Before finishing: you made changes in territory with NO recorded precedent "
           f"({', '.join(scopes) or 'a risky action'}). If you made a decision there (a pattern, a "
           "library/data-store choice, a reuse/canonical-source call), RECORD it so the next agent "
           'inherits it: npx precedent-cli record "situation; decided X; because Y; scope <paths>". '
           "If nothing worth recording, you may stop.")
    print(json.dumps({"decision": "block", "reason": msg,
                      "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
