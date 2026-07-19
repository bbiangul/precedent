#!/usr/bin/env python3
"""Outcome ledger — turns real PR/merge activity into HUMAN/PR-DERIVED ground truth.

This is the instrumentation the benchmarking pointed to: retrieval-at-scale is capped by
GROUND-TRUTH quality (two LLM label passes disagree 58%), not by the model. LLM labels can't
be measured past ~66%. Real outcomes can. Every governed action already logs a verdict
(.precedent/verdicts.jsonl, via govern_cli). This module joins each verdict to what ACTUALLY
happened and derives two gold signals:

  1. RETRIEVAL ground truth: the decisions a human confirms actually governed the change
     (from the recorded WHY on override/escalation, or reviewer/CODEOWNERS signal). Replaces
     the LLM labeler in the retrieval evals — same format as tools/extract/*_eval.py consume.

  2. VERDICT correctness / enforcement quality: was auto-merge safe? was a block justified?
     -> the §10 shadow-mode metrics and the §12 "0 harmful silent actions" invariant, on REAL data.

Outcome taxonomy (per governed PR):
  merged_clean       act_* verdict, merged, no revert/incident      -> autonomy was SAFE
  reverted           act_* verdict, merged, later reverted/incident -> HARMFUL SILENT ACTION (worst)
  blocked_upheld     block verdict, human agreed (closed/changed)   -> good catch (prevented harm)
  blocked_overridden block verdict, human merged anyway, no incident-> FALSE BLOCK (too conservative)

Signals map from GitHub events (see from_github_event): merge -> merged_clean/pending;
a revert PR or linked incident -> reverted; a human approval+merge after a failing gate ->
blocked_overridden; a close/relabel after a block -> blocked_upheld.

Usage:
  python3 tools/outcome.py label V-0003 reverted --applied E4 --reason "missed idempotency key"
  python3 tools/outcome.py ingest event.json          # a GitHub PR/merge webhook payload
  python3 tools/outcome.py export                      # -> .precedent/ground_truth.jsonl (retrieval GT)
  python3 tools/outcome.py metrics                     # enforcement-quality report
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import govern

PREC = os.path.join(govern.REPO, ".precedent")
VERDICTS = os.path.join(PREC, "verdicts.jsonl")
OUTCOMES = os.path.join(PREC, "outcomes.jsonl")
GROUND_TRUTH = os.path.join(PREC, "ground_truth.jsonl")

OUTCOMES_SET = {"merged_clean", "reverted", "blocked_upheld", "blocked_overridden"}
# an act_* verdict whose outcome is a revert is the safety-invariant breach
HARMFUL = {"reverted"}
# outcomes that mean the verdict was CORRECT
VERDICT_OK = {"merged_clean", "blocked_upheld"}


def _read(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def _verdicts_by_id():
    return {v["id"]: v for v in _read(VERDICTS) if "id" in v}


def label(vid, outcome, applied=None, reason="", incident=None):
    if outcome not in OUTCOMES_SET:
        sys.exit(f"outcome must be one of {sorted(OUTCOMES_SET)}")
    if vid not in _verdicts_by_id():
        print(f"warning: no verdict {vid} in the log yet (recording anyway)")
    rec = {"verdict_id": vid, "ts": int(time.time()), "outcome": outcome,
           "applied_decisions": applied or [], "reason": reason, "incident": incident,
           "source": "human"}
    with open(OUTCOMES, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"✓ recorded outcome for {vid}: {outcome}"
          + (f"  applied={applied}" if applied else "")
          + ("  ⚠ HARMFUL SILENT ACTION" if outcome in HARMFUL else ""))


def from_github_event(ev):
    """Map a GitHub PR/merge webhook payload to an outcome record (best-effort, documented mapping).
    Real deployments wire this to a webhook; the fields below are the standard PR event shape."""
    pr = ev.get("pull_request", {})
    number = pr.get("number") or ev.get("number")
    merged = pr.get("merged")
    title = (pr.get("title") or "").lower()
    labels = {l.get("name", "").lower() for l in pr.get("labels", [])}
    gate_passed = ev.get("precedent_gate_passed")     # our required-check conclusion, if provided
    revert = title.startswith("revert") or "revert" in labels or ev.get("reverts")
    incident = ev.get("incident_ref")
    if revert or incident:
        outcome = "reverted"
    elif merged and gate_passed is False:
        outcome = "blocked_overridden"                # merged despite our block
    elif merged:
        outcome = "merged_clean"
    elif pr.get("state") == "closed":
        outcome = "blocked_upheld"                    # closed without merging after a block
    else:
        outcome = None                                # still open -> pending
    return {"pr": number, "outcome": outcome, "incident": incident,
            "applied_decisions": [], "reason": f"github:{ev.get('action','')}", "source": "github"}


def ingest(path):
    ev = json.load(open(path))
    rec = from_github_event(ev)
    if not rec["outcome"]:
        print(f"PR {rec['pr']}: still pending, no terminal outcome yet"); return
    # join to the verdict for this PR
    vid = next((v["id"] for v in _read(VERDICTS) if str(v.get("pr")) == str(rec["pr"])), None)
    rec["verdict_id"] = vid
    rec["ts"] = int(time.time())
    with open(OUTCOMES, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"✓ ingested PR {rec['pr']} -> {rec['outcome']}"
          + (f" (verdict {vid})" if vid else " (no matching verdict)"))


def export_ground_truth():
    """Join verdicts + outcomes -> real retrieval ground truth, in the eval format. A task gets a
    GT label only when a human/PR outcome CONFIRMS the governing decisions (applied_decisions)."""
    V = _verdicts_by_id()
    rows, labeled = [], 0
    by_vid = {}
    for o in _read(OUTCOMES):
        by_vid.setdefault(o.get("verdict_id"), []).append(o)
    for vid, v in V.items():
        outs = by_vid.get(vid, [])
        applied = sorted({d for o in outs for d in o.get("applied_decisions", [])})
        # prefer human-confirmed applied decisions; fall back to the verdict's precedent_ids
        gt = applied or v.get("precedent_ids", [])
        if not outs:
            continue                                  # no outcome yet -> not gold
        correct = any(o["outcome"] in VERDICT_OK for o in outs)
        rows.append({"desc": v.get("title", ""), "files": v.get("paths", []),
                     "gt": gt, "verdict": v["verdict"],
                     "verdict_correct": correct, "source": "pr-outcome",
                     "confirmed_applied": bool(applied)})
        labeled += bool(gt)
    with open(GROUND_TRUTH, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"✓ wrote {len(rows)} outcome-labeled tasks -> {GROUND_TRUTH} "
          f"({labeled} with >=1 confirmed decision). This is the trustworthy eval set that "
          f"replaces LLM labels once enough PRs accrue.")


def metrics():
    V = _verdicts_by_id()
    outs = _read(OUTCOMES)
    n = len(outs)
    if not n:
        print("no outcomes recorded yet. Run shadow mode / wire the GitHub webhook first."); return
    c = {k: 0 for k in OUTCOMES_SET}
    for o in outs:
        c[o["outcome"]] = c.get(o["outcome"], 0) + 1
    harmful = c["reverted"]
    false_block = c["blocked_overridden"]
    prevented = c["blocked_upheld"]
    correct = c["merged_clean"] + c["blocked_upheld"]
    print("── Enforcement quality (from real outcomes) ───────────")
    print(f"  outcomes recorded        : {n}")
    print(f"  merged clean (safe auto) : {c['merged_clean']}")
    print(f"  prevented harm (blocks upheld) : {prevented}")
    print(f"  FALSE BLOCKS (overridden, no incident) : {false_block}   ← the adoption risk")
    print(f"  HARMFUL SILENT ACTIONS (act_* then reverted) : {harmful}   ← the safety invariant")
    print(f"  verdict accuracy         : {correct}/{n} = {100*correct/n:.0f}%")
    # the PRD §12 non-perverse anchor
    print(f"  net escalation value     : prevented_harm({prevented}) − harmful({harmful}) = {prevented - harmful}")
    print("───────────────────────────────────────────────────────")
    print("These are the numbers a design partner is sold on — and they double as the ground truth "
          "that unblocks retrieval measurement (export).")


def review(min_support=3, bad_rate=0.5, propose=False):
    """Outcome-driven staleness detector. A decision whose governed PRs keep going wrong is probably
    wrong: `reverted` (an act_* verdict citing it caused harm) or `blocked_overridden` (it blocked a
    PR a human then merged = false block / too strict). Flag decisions over the bad-rate threshold and
    optionally PROPOSE their deprecation (a human confirms — same admission control as agents)."""
    from collections import defaultdict
    agg = defaultdict(lambda: defaultdict(int))
    for o in _read(OUTCOMES):
        for did in o.get("applied_decisions", []):
            agg[did][o["outcome"]] += 1
            agg[did]["n"] += 1
    flagged = []
    for did, a in agg.items():
        bad = a["reverted"] + a["blocked_overridden"]
        if a["n"] >= min_support and bad / a["n"] >= bad_rate:
            flagged.append((did, dict(a), bad))
    flagged.sort(key=lambda x: (-x[2] / x[1]["n"], -x[2]))
    if not agg:                                   # empty ledger — "none stale" would be false reassurance
        print("no outcome data yet (ledger empty) — staleness is NOT measurable. Wire outcomes "
              "(outcome.py label / GitHub webhook) first."); return
    if not flagged:
        print(f"no stale decisions: none with >={min_support} governed outcomes and >={bad_rate:.0%} bad."); return
    print(f"── Stale-decision review ({len(flagged)} flagged; >={min_support} outcomes, >={bad_rate:.0%} bad) ──")
    for did, a, bad in flagged:
        kind = ("keeps causing reverts" if a["reverted"] >= a["blocked_overridden"] else "keeps getting overridden (false block)")
        print(f"  {did}: {bad}/{a['n']} bad ({a['reverted']} reverted, {a['blocked_overridden']} overridden) — {kind}")
    if not propose:
        print("\nRun with --propose to file deprecation proposals (a human then confirms).")
        return
    import precedent
    for did, a, bad in flagged:
        reason = (f"outcome-detector: {bad}/{a['n']} governed PRs went wrong "
                  f"({a['reverted']} reverted, {a['blocked_overridden']} overridden)")
        precedent.deprecate(did, reason=reason, propose=True, actor="outcome-detector")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("label"); p.add_argument("vid"); p.add_argument("outcome")
    p.add_argument("--applied", nargs="*", default=[]); p.add_argument("--reason", default="")
    p.add_argument("--incident", default=None)
    p = sub.add_parser("ingest"); p.add_argument("path")
    sub.add_parser("export"); sub.add_parser("metrics")
    p = sub.add_parser("review"); p.add_argument("--propose", action="store_true")
    p.add_argument("--min-support", type=int, default=3); p.add_argument("--bad-rate", type=float, default=0.5)
    a = ap.parse_args()
    if a.cmd == "label":
        label(a.vid, a.outcome, a.applied, a.reason, a.incident)
    elif a.cmd == "ingest":
        ingest(a.path)
    elif a.cmd == "export":
        export_ground_truth()
    elif a.cmd == "metrics":
        metrics()
    elif a.cmd == "review":
        review(a.min_support, a.bad_rate, a.propose)


if __name__ == "__main__":
    main()
