#!/usr/bin/env python3
"""Tamper-evidence for the decision ledger.

`events.jsonl` is a HASH CHAIN: each event seals the previous one (prev = last event's hash; hash =
sha256 of this event). `verify` walks the chain and cross-checks the live store, so a decision or an
audit event that was edited, removed, or reordered OUTSIDE the normal flow is detected — that's what
makes "decision of record" tamper-evident, not just a mutable table.

  python3 src/verify.py            # check the chain + decision anchoring
  python3 src/verify.py anchor     # seal every current active decision into the ledger (for seed/sync)
"""
import json, os, sys, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import precedent


def _recompute(ev):
    e = {k: v for k, v in ev.items() if k != "hash"}
    return hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest()


def verify():
    path = precedent.EVENTS
    if not os.path.exists(path):
        print("no ledger yet (.precedent/events.jsonl) — nothing to verify."); return 0
    events = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            print("⚠ TAMPERING: ledger has a non-JSON line — corrupted."); return 1
    # 1. chain integrity — every event's content hash + prev-link must hold
    prev = "genesis"; broken = []
    for i, ev in enumerate(events):
        if _recompute(ev) != ev.get("hash"):
            broken.append((i, ev.get("kind"), "content edited"))
        elif ev.get("prev") != prev:
            broken.append((i, ev.get("kind"), "removed/reordered"))
        prev = ev.get("hash", "")
    if broken:
        print(f"⚠ TAMPERING DETECTED — ledger chain broken at {len(broken)} point(s):")
        for i, k, why in broken[:6]:
            print(f"    event #{i} ({k}): {why}")
        return 1
    print(f"✓ ledger intact — {len(events)} events, hash chain verified")
    # 2. decision anchoring — a decision's current content must match its sealed hash
    anchored = {}
    for ev in events:
        if ev.get("kind") in ("record", "anchor") and ev.get("content_hash"):
            anchored[ev.get("id")] = ev["content_hash"]
    decs = precedent._all_precedents()
    altered, unanchored, ok = [], [], 0
    for d in decs:
        h = precedent._decision_hash(d)
        if d["id"] in anchored:
            if anchored[d["id"]] == h:
                ok += 1
            else:
                altered.append(d["id"])
        else:
            unanchored.append(d["id"])
    if altered:
        print(f"⚠ TAMPERING DETECTED — {len(altered)} decision(s) altered outside the ledger: {altered}")
        return 1
    msg = f"✓ decisions: {ok} anchored + verified"
    if unanchored:
        msg += f"  ·  {len(unanchored)} unanchored (from seed/sync) — run `verify anchor` to seal them"
    print(msg)
    return 0


def anchor():
    decs = precedent._all_precedents()
    for d in decs:
        precedent._log_event("anchor", id=d["id"], content_hash=precedent._decision_hash(d))
    print(f"✓ sealed {len(decs)} decisions into the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(anchor() if (len(sys.argv) > 1 and sys.argv[1] == "anchor") else verify())
