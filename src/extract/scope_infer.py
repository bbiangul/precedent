#!/usr/bin/env python3
"""Content-based scope inference — the real test of the scope-pruning lever.

Real conventions are written centrally, so source-path scoping yields 0 scoped decisions.
Instead, infer WHICH CODE AREA each decision governs from its content, constrained to the
repo's real module structure. Measures the honest scoped-vs-global fraction — which decides
whether scope-pruning is a real lever or mostly inapplicable on real data.

Usage: OPENROUTER_API_KEY=... python3 tools/extract/scope_infer.py [real_decisions.json]
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import precedent

# Real Backstage areas -> real path globs
AREAS = {
    "catalog":      ["plugins/catalog/**", "plugins/catalog-*/**"],
    "scaffolder":   ["plugins/scaffolder/**", "plugins/scaffolder-*/**"],
    "techdocs":     ["plugins/techdocs/**", "plugins/techdocs-*/**"],
    "search":       ["plugins/search/**", "plugins/search-*/**"],
    "auth":         ["plugins/auth/**", "plugins/auth-*/**"],
    "permission":   ["plugins/permission/**", "plugins/permission-*/**"],
    "kubernetes":   ["plugins/kubernetes/**", "plugins/kubernetes-*/**"],
    "frontend-ui":  ["packages/core-components/**", "packages/core-plugin-api/**", "packages/app-defaults/**"],
    "backend":      ["packages/backend-*/**", "plugins/*-backend/**"],
    "cli-build":    ["packages/cli/**", "packages/build-utils/**", "packages/eslint-plugin/**"],
    "config":       ["packages/config/**", "packages/config-loader/**"],
    "testing":      ["packages/test-utils/**", "packages/frontend-test-utils/**", "packages/backend-test-utils/**"],
}
AREA_LIST = ", ".join(AREAS) + ", global"

def classify(batch):
    lines = "\n".join(f'{d["id"]}: {d["decision"]}' for d in batch)
    out = precedent._llm(
        "For each engineering decision, output the SINGLE code area it primarily governs, chosen ONLY "
        f"from: [{AREA_LIST}]. Use 'global' if it applies repo-wide (most style/process/general rules ARE "
        "global — do not force a scope). Output STRICT JSON {\"<id>\":\"<area>\", ...}.\n\n" + lines,
        json_mode=True, max_tokens=3000)
    if not out:
        return {}
    m = re.search(r"\{.*\}", out, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}

def main(path):
    data = json.load(open(path))
    decs = data["decisions"]
    for i in range(0, len(decs), 20):
        batch = decs[i:i + 20]
        cls = classify(batch)
        for d in batch:
            area = cls.get(d["id"], "global")
            d["scope"] = {"paths": AREAS.get(area, [])}   # unknown/global -> []
        print(f"  {min(i+20, len(decs))}/{len(decs)} classified", flush=True)
    json.dump(data, open(path, "w"), indent=2)
    from collections import Counter
    scoped = sum(1 for d in decs if d["scope"]["paths"])
    print(f"\nscoped: {scoped} / global: {len(decs)-scoped}  ({100*scoped/len(decs):.0f}% scopeable)")
    areas = Counter()
    for d in decs:
        for a, g in AREAS.items():
            if d["scope"]["paths"] == g:
                areas[a] += 1
    print("by area:", dict(areas.most_common()))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "real_decisions.json"))
