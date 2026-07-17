#!/usr/bin/env python3
"""Record-time ENRICHMENT — make a recorded decision findable by the situations that should trigger it.

Retrieval is the #1 bottleneck (~66%), and the worst misses are vocabulary gaps: the decision says
"feature flags go through the superadmin DB registry" but the agent asks "add a feature flag behind an
env var" — opposite words, no lexical/semantic overlap. Enrichment closes that gap AT WRITE TIME (the
cheap, one-shot moment) by attaching to each decision:
  - triggers    : the situations/tasks that SHOULD retrieve this decision (HyPE-at-write)
  - anti_pattern : the wrong approach it forbids (so a query phrased as the mistake still matches)
  - keywords    : canonical entities/synonyms/aliases

The enriched text is what gets indexed (bm25 + embeddings). The human-facing `decision` stays clean.

enrich_decision(decision, reasoning) -> {triggers, anti_pattern, keywords}
enriched_text(dec)                    -> the string to index for retrieval
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precedent


def enrich_decision(decision, reasoning=""):
    out = precedent._llm(
        "You are enriching a recorded engineering decision so future retrieval finds it from the "
        "situations that should trigger it. Given the DECISION, output STRICT JSON:\n"
        '{"triggers":["<short task/situation phrasing an engineer or agent would type that this '
        'decision must govern>", ...4-6],"anti_pattern":"<the WRONG approach this forbids, one '
        'phrase>","keywords":["<canonical entity/synonym/alias>", ...3-6]}\n'
        "Make triggers VARIED in vocabulary (include the words someone would use when about to do the "
        "WRONG thing — e.g. if the rule mandates DB-registered flags, a trigger is 'add a feature flag "
        "behind an env var'). Be specific to THIS decision.\n\n"
        f"DECISION: {decision}\nWHY: {reasoning}", json_mode=True, max_tokens=400)
    d = {}
    if out:
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
            except Exception:
                d = {}
    return {"triggers": [str(t) for t in d.get("triggers", [])][:6],
            "anti_pattern": str(d.get("anti_pattern", "")),
            "keywords": [str(k) for k in d.get("keywords", [])][:6]}


def enriched_text(dec):
    """The string to index: human decision + reasoning + enrichment (if present)."""
    parts = [dec.get("decision", ""), dec.get("reasoning", "")]
    e = dec.get("enrichment") or {}
    parts += e.get("triggers", [])
    if e.get("anti_pattern"):
        parts.append("avoid: " + e["anti_pattern"])
    parts += e.get("keywords", [])
    return " ".join(p for p in parts if p)


if __name__ == "__main__":
    dec = sys.argv[1] if len(sys.argv) > 1 else \
        "Feature flags must be registered in the superadmin database, not gated by environment variables."
    print(json.dumps(enrich_decision(dec), indent=2))
