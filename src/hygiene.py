#!/usr/bin/env python3
"""Hygiene pass — the store's "sanitization" job. Runs OFF the write path (record stays cheap) and
surfaces problems as PROPOSALS a human confirms, never silent edits:

  1. CONTRADICTIONS — two active decisions that can't both be followed (e.g. "cache with Redis" vs
     "cache with Memcached" on overlapping scope). Only near-neighbours are LLM-judged, so cost is
     O(store) embeddings + a few judgments, not O(n^2).
  2. OUTCOME STALENESS — decisions whose governed PRs keep going wrong (reverted / overridden).
     (folds in outcome.review)

Run it nightly / in CI / on demand — never inline on record:
  python3 src/hygiene.py            # report
  python3 src/hygiene.py --propose  # file deprecation proposals (human confirms)
"""
import json, os, re, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import govern, precedent, retrieval

SIM_MIN = float(os.environ.get("PRECEDENT_HYGIENE_SIM", "0.55"))   # only judge topically-close pairs
MAX_JUDGE = int(os.environ.get("PRECEDENT_HYGIENE_MAX", "200"))    # cap LLM judgments per run


def _paths(d):
    return d.get("scope", {}).get("paths", d.get("scope_paths", [])) or []

def _scope_overlaps(a, b):
    pa, pb = _paths(a), _paths(b)
    if not pa or not pb or pa == ["**"] or pb == ["**"]:
        return True                                   # global on either side overlaps everything
    return bool(set(pa) & set(pb)) or any(x.split("/")[0] == y.split("/")[0] for x in pa for y in pb)

def _contradict(a, b):
    out = precedent._llm(
        "Two team engineering rules. Do they CONTRADICT — i.e. a change can't satisfy both at once "
        "(mutually exclusive mandates)? Two rules on the same topic that can BOTH hold (e.g. 'use Redis' "
        "+ 'set a TTL') do NOT contradict. Output STRICT JSON {\"contradict\":<bool>,\"why\":\"<short>\"}.\n\n"
        f"RULE A: {a['decision']}\nRULE B: {b['decision']}")
    if not out:
        return None
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except Exception:
        return None
    return d if d.get("contradict") else None

def contradictions(decs):
    if len(decs) < 2:
        return []
    vecs = retrieval._embed([retrieval._dtext(d) for d in decs])
    def nrm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    vecs = [nrm(v) for v in vecs]
    pairs = []
    for i in range(len(decs)):
        for j in range(i + 1, len(decs)):
            s = sum(x * y for x, y in zip(vecs[i], vecs[j]))
            if s >= SIM_MIN and _scope_overlaps(decs[i], decs[j]):
                pairs.append((s, i, j))
    pairs.sort(reverse=True)
    found = []
    for _, i, j in pairs[:MAX_JUDGE]:
        c = _contradict(decs[i], decs[j])
        if c:
            found.append((decs[i], decs[j], c.get("why", "")))
    return found

_RANK = {"guardrail": 3, "policy": 2, "precedent": 1, "mined": 0, "unconfirmed": 0}
def _weaker(a, b):
    return a if _RANK.get(a.get("authority"), 0) <= _RANK.get(b.get("authority"), 0) else b

def main(propose=False):
    decs = [d for d in govern.DECISIONS if govern.is_active(d)]
    print(f"── Hygiene pass ({len(decs)} active decisions) ──\n")
    # 1. contradictions
    con = contradictions(decs)
    print(f"CONTRADICTIONS: {len(con)}")
    proposals = []
    for a, b, why in con:
        w = _weaker(a, b); other = b if w is a else a
        tie = _RANK.get(a.get("authority"), 0) == _RANK.get(b.get("authority"), 0)
        print(f"  {a['id']} ⟂ {b['id']}: {why}")
        if tie:
            print(f"    → same authority — needs a human to pick a winner")
        else:
            print(f"    → propose retiring the weaker {w['id']} (superseded by {other['id']})")
            proposals.append((w["id"], f"hygiene: contradicts {other['id']} ({why})", other["id"]))
    # 2. outcome staleness (fold in the outcome detector)
    print()
    try:
        import outcome
        outcome.review(propose=False)
    except Exception as e:
        print(f"outcome review unavailable: {e}")
    # file proposals
    if propose and proposals:
        print(f"\nfiling {len(proposals)} contradiction proposals (human confirms):")
        for did, reason, sup in proposals:
            precedent.deprecate(did, reason=reason, superseded_by=sup, propose=True, actor="hygiene")
    elif proposals:
        print("\nRun with --propose to file contradiction proposals (and `outcome.py review --propose` for staleness).")

if __name__ == "__main__":
    main(propose="--propose" in sys.argv)
