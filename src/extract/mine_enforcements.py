#!/usr/bin/env python3
"""Enforcement-mining extractor — seed the precedent store from PR REVIEW HISTORY.

The reviewer-enforcement backtest found 0% of the rules reviewers actually enforce are in the
ADR/BEP-extracted store (they're tacit — in reviewers' heads and PR comments). This pipeline mines
them: every PR review comment where a reviewer enforced a convention becomes a candidate decision,
near-duplicates are CLUSTERED (the same rule enforced across many PRs collapses to one), and
enforcement FREQUENCY becomes an authority signal (enforced 10x = a real policy/guardrail; once = a
precedent). Output matches the decision-store schema, with provenance and a `status: mined` flag so a
human promotes before it becomes binding (admission control, §8).

Pipeline: comments -> classify+extract rule (LLM) -> embed+cluster rules -> per cluster:
canonicalize (LLM) + authority-from-frequency+language + scope-from-paths + provenance.

Usage:
  # fetch first (any repo):
  gh api "/repos/OWNER/REPO/pulls/comments?sort=created&direction=desc&per_page=100&page=N" ...
  OPENROUTER_API_KEY=... python3 tools/extract/mine_enforcements.py [comments.json] [out.json]
"""
import json, math, os, re, sys
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import precedent, retrieval

COMMENTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "review_comments.json")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "mined_decisions.json")
SIM = 0.80                      # cluster threshold on rule embeddings
STRONG = re.compile(r"\b(must|never|always|require|required|prohibit|forbidden|shall|do not|don't)\b", re.I)


def _json(out):
    if not out:
        return None
    m = re.search(r"\{.*\}", out, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def classify(c):
    """Reviewer enforcing a convention? -> extract the general rule + a short reason."""
    d = _json(precedent._llm(
        "A code reviewer left this PR comment. Decide if it ENFORCES a team CONVENTION/STANDARD/RULE "
        "(telling the author to change the code to match how this team does things) — not a question, "
        "praise, typo nit, or discussion. If yes, give the general RULE as one imperative sentence and a "
        "short WHY. STRICT JSON {\"enforcement\":<bool>,\"rule\":\"...\",\"why\":\"...\"}.\n\n"
        f"FILE: {c['path']}\nCODE:\n{c['diff_hunk'][:800]}\n\nCOMMENT:\n{c['body'][:600]}",
        json_mode=True, max_tokens=250))
    if d and d.get("enforcement") and d.get("rule"):
        return {"rule": d["rule"].strip(), "why": d.get("why", ""), "path": c["path"], "pr": c["pr"],
                "quote": c["body"][:200]}
    return None


def cluster(items, vecs):
    """greedy agglomerative on normalized rule embeddings."""
    clusters = []
    for i, v in enumerate(vecs):
        best, bs = -1, 0.0
        for ci, cl in enumerate(clusters):
            s = sum(a * b for a, b in zip(v, cl["centroid"]))
            if s > bs:
                bs, best = s, ci
        if bs >= SIM:
            cl = clusters[best]; cl["idx"].append(i)
            m = len(cl["idx"])
            cl["centroid"] = [(cl["centroid"][j] * (m - 1) + v[j]) / m for j in range(len(v))]
        else:
            clusters.append({"idx": [i], "centroid": list(v)})
    return [[items[i] for i in c["idx"]] for c in clusters]


def scope_for(paths):
    globs = set()
    spread = set()
    for p in paths:
        m = re.match(r"(plugins|packages)/([^/]+)/", p)
        if m:
            globs.add(f"{m.group(1)}/{m.group(2)}/**"); spread.add(m.group(2))
    # enforced across many modules -> cross-cutting -> leave global (no path prefilter)
    if len(spread) >= 3:
        return []
    return sorted(globs)


def canonicalize(members):
    rules = "\n".join(f"- {m['rule']}" for m in members[:12])
    d = _json(precedent._llm(
        "These are near-duplicate team rules mined from PR review comments. Merge them into ONE "
        "canonical rule. Output STRICT JSON {\"decision\":\"one imperative sentence\",\"reasoning\":\"short why\","
        "\"category\":\"tech|design|process|product\"}.\n\n" + rules, json_mode=True, max_tokens=250))
    return d or {"decision": members[0]["rule"], "reasoning": members[0].get("why", ""), "category": "tech"}


def authority(members, decision):
    """frequency + language -> proposed authority (human promotes; everything enters as mined)."""
    support = len(members)
    strong = bool(STRONG.search(decision)) or any(STRONG.search(m["rule"]) for m in members)
    if support >= 8 or (strong and support >= 3):
        return "guardrail"
    if support >= 3 or strong:
        return "policy"
    return "precedent"


def main():
    raw = json.load(open(COMMENTS))
    cand = [c for c in raw if len(c.get("diff_hunk", "")) > 40 and len(c.get("body", "")) > 15]
    print(f"{len(raw)} review comments; {len(cand)} substantive; classifying enforcements...", flush=True)
    with ThreadPoolExecutor(max_workers=12) as ex:
        enf = [r for r in ex.map(classify, cand) if r]
    print(f"enforcements: {len(enf)} ({100*len(enf)/len(cand):.0f}% of reviewed changes). "
          "embedding + clustering rules...", flush=True)
    vecs = retrieval._embed([e["rule"] for e in enf])
    # normalize
    def nrm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]
    vecs = [nrm(v) for v in vecs]
    clusters = cluster(enf, vecs)
    clusters.sort(key=len, reverse=True)
    print(f"{len(clusters)} distinct decisions after clustering "
          f"(largest cluster: {len(clusters[0])} enforcements)\n", flush=True)

    def build(i_cl):
        i, members = i_cl
        can = canonicalize(members) if len(members) > 1 else \
            {"decision": members[0]["rule"], "reasoning": members[0].get("why", ""), "category": "tech"}
        paths = [m["path"] for m in members]
        return {"id": f"RV-{i+1:04d}", "decision": can["decision"], "reasoning": can.get("reasoning", ""),
                "authority": authority(members, can["decision"]), "category": can.get("category", "tech"),
                "scope": {"paths": scope_for(paths)}, "support": len(members), "status": "mined",
                "provenance": [{"pr": m["pr"], "path": m["path"], "quote": m["quote"]} for m in members[:5]]}
    with ThreadPoolExecutor(max_workers=12) as ex:
        decisions = list(ex.map(build, list(enumerate(clusters))))

    json.dump({"decisions": decisions}, open(OUT, "w"), indent=2)
    from collections import Counter
    print(f"wrote {len(decisions)} MINED decisions -> {OUT}")
    print("authority (proposed):", dict(Counter(d["authority"] for d in decisions)))
    print("scoped:", sum(1 for d in decisions if d["scope"]["paths"]),
          "/ global:", sum(1 for d in decisions if not d["scope"]["paths"]))
    print("multiply-enforced (support>=3):", sum(1 for d in decisions if d["support"] >= 3))
    print("\nTop decisions by enforcement frequency (the ones reviewers care most about):")
    for d in sorted(decisions, key=lambda x: -x["support"])[:6]:
        print(f"  [{d['authority']:9} x{d['support']:<2} {d['scope']['paths'] or 'global'}] {d['decision'][:80]}")
    print("\nAll enter as status='mined' (unconfirmed) — a human promotes before binding (admission control).")


if __name__ == "__main__":
    main()
