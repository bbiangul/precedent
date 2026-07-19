#!/usr/bin/env python3
"""Close the loop: measure retrieval + verdict accuracy on the REAL PR-derived ground truth
(.precedent/ground_truth.jsonl, produced by outcome.py export) instead of LLM labels.

This is the reusable consumer that, once a design partner's PRs accrue, yields the trustworthy
recall number the lab couldn't (LLM labels capped ~66% with 58% self-disagreement). Same store
the product governs; same soft retrieval as the hot path.

Usage: OPENROUTER_API_KEY=... python3 .precedent/engine/eval_on_ground_truth.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import govern, precedent, retrieval

GT_FILE = os.path.join(govern.REPO, ".precedent", "ground_truth.jsonl")


def main():
    if not os.path.exists(GT_FILE):
        sys.exit("no ground_truth.jsonl yet — run: npx precedent-cli outcome export")
    rows = [json.loads(l) for l in open(GT_FILE)]
    store = precedent._all_precedents()
    retr = [r for r in rows if r.get("gt")]                    # tasks with a confirmed decision
    print(f"real PR-derived ground truth: {len(rows)} tasks ({len(retr)} with a confirmed decision)\n")

    # 1) retrieval recall on real labels (the number the lab couldn't trust)
    R = 0
    for r in retr:
        try:
            ids = set(retrieval.soft(r["desc"], store, files=r["files"], k=20)[0])
        except Exception:
            ids = set(retrieval.scope(r["desc"], store, files=r["files"])[0]) \
                | set(retrieval.bm25(r["desc"], store, k=20)[0])
        R += len(ids & set(r["gt"])) / len(r["gt"])
    print(f"retrieval recall @real-GT : {R/len(retr)*100:.0f}%  (n={len(retr)})"
          if retr else "no retrieval-labeled tasks yet")

    # 2) verdict accuracy on real outcomes
    ok = sum(1 for r in rows if r.get("verdict_correct"))
    print(f"verdict accuracy @outcomes: {ok/len(rows)*100:.0f}%  (n={len(rows)})")
    print("\nAt a design partner this replaces every LLM-labeled number in the retrieval/DECIDE-Bench "
          "evals — trustworthy because the labels are what actually happened on real PRs.")


if __name__ == "__main__":
    main()
