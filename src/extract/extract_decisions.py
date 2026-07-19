#!/usr/bin/env python3
"""Extract REAL decisions from a real repo — the product's offline extraction pipeline.

Mines a cloned repo for atomic team decisions from ADRs, enhancement proposals (BEPs/RFCs),
and convention docs, assigns authority (guardrail/policy/precedent), category, and scope
(from the source path + CODEOWNERS). Produces a real corpus with a REAL authority/category/
scope distribution — which kills the synthetic structural-leak problem for free.

Usage: OPENROUTER_API_KEY=... ARM_MODEL=google/gemini-2.5-flash \
       python3 tools/extract/extract_decisions.py <repo_path> [out.json]
"""
import glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import precedent

def scope_for(relpath):
    m = re.match(r"(plugins|packages)/([^/]+)/", relpath)
    return [f"{m.group(1)}/{m.group(2)}/**"] if m else []   # else global/unscoped (realistic)

def gather(repo, cap=140):
    docs, seen = [], set()
    def add(kind, p):
        rp = os.path.abspath(p)                     # a file matched by several globs is processed once
        if rp in seen:
            return
        seen.add(rp)
        docs.append((kind, p))
    for p in sorted(glob.glob(os.path.join(repo, "docs/architecture-decisions/adr0*.md"))):
        if "template" not in p:
            add("ADR", p)
    for p in sorted(glob.glob(os.path.join(repo, "beps/*/README.md"))):
        add("BEP", p)
    kw = re.compile(r"contribut|convention|style|naming|test|best.?practic|guideline|structure|"
                    r"standard|pattern|architect|design|security|api-|lint|format|review|deprecat|"
                    r"migrat|error|config|auth|permission", re.I)
    conv = [p for p in glob.glob(os.path.join(repo, "docs/**/*.md"), recursive=True)
            if kw.search(os.path.relpath(p, repo)) and "node_modules" not in p]
    for p in sorted(set(conv))[:cap]:
        add("CONVENTION", p)
    return docs

def extract(text, source_kind, relpath):
    out = precedent._llm(
        "From this engineering document, extract every ATOMIC, actionable team DECISION an AI coding "
        "agent working in this repo would need to FOLLOW (a convention/rule/standard). Output STRICT JSON "
        '{"decisions":[{"decision":"one sentence rule","reasoning":"why (short)","authority":"guardrail|policy|precedent","category":"tech|design|product|process"}]}. '
        "authority: guardrail = a hard MUST/NEVER; policy = a standard/should; precedent = a preference. "
        "Extract ONLY real, followable decisions (not history/background/prose). If none, decisions=[].\n\n"
        f"SOURCE ({source_kind} {relpath}):\n{text[:6000]}", json_mode=True, max_tokens=2500)
    if not out:
        return []
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0)).get("decisions", [])
    except Exception:
        return []

def main(repo, outp):
    docs = gather(repo)
    print(f"source docs: {len(docs)} (ADR/BEP/CONVENTION)", flush=True)
    # LLM extraction is non-deterministic — a single pass can miss a doc entirely or
    # only part of it. Run PASSES per doc and union (the dedup below collapses overlap),
    # which recovers whole-doc and partial misses. More passes = better recall, more calls.
    passes = int(os.environ.get("PRECEDENT_EXTRACT_PASSES", "2"))
    decisions, seen_txt = [], set()
    for kind, path in docs:
        rel = os.path.relpath(path, repo)
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for _ in range(passes):
            for d in extract(text, kind, rel):
                if not isinstance(d, dict) or not d.get("decision"):
                    continue
                norm = re.sub(r"[^a-z0-9]+", "", d["decision"].lower())   # drop near-identical restatements
                if norm in seen_txt:
                    continue
                seen_txt.add(norm)
                decisions.append({
                    "id": f"BS-{len(decisions)+1:04d}",
                    "decision": d["decision"], "reasoning": d.get("reasoning", ""),
                    "authority": d.get("authority", "policy") if d.get("authority") in ("guardrail","policy","precedent") else "policy",
                    "category": d.get("category", "tech"),
                    "scope": {"paths": scope_for(rel)}, "source": rel})
        print(f"  {rel}: {len(decisions)} total", flush=True)
    json.dump({"decisions": decisions}, open(outp, "w"), indent=2)
    # distribution report
    from collections import Counter
    print(f"\nwrote {len(decisions)} REAL decisions -> {outp}")
    print("authority:", dict(Counter(d["authority"] for d in decisions)))
    print("category:", dict(Counter(d["category"] for d in decisions)))
    print("scoped:", sum(1 for d in decisions if d["scope"]["paths"]), "/ global:",
          sum(1 for d in decisions if not d["scope"]["paths"]))

if __name__ == "__main__":
    repo = sys.argv[1]
    outp = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "real_decisions.json")
    main(repo, outp)
