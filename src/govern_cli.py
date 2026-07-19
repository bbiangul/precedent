#!/usr/bin/env python3
"""govern(diff) — the v1 hero. The permission path for coding-agent autonomy.

Composes the whole loop for one proposed change:
  1. RETRIEVE  the applicable precedents from the org's store  (corrected retrieval: §6.2)
  2. JUDGE     authority_state (match/conflict) + consequentiality  (model — the semantic half)
  3. RESOLVE   risk tier + autonomy matrix -> a single verdict     (deterministic — govern.py)
  4. ENFORCE   exit 0 = allow auto-merge, exit 1 = block           (the GitHub required check)
  5. CAPTURE   on block, prompt for the WHY so it becomes a precedent
  6. LOG       every verdict to .precedent/verdicts.jsonl          (the autonomy-frontier feed)

Split of labor is the point: the MODEL only judges which precedent applies and whether the
change matches or conflicts; DETERMINISTIC code derives risk and applies the matrix. That
keeps the verdict model-independent, fast, auditable, and ours.

Usage:
  npx precedent-cli govern                       # gate the current PR (git diff vs base)
  npx precedent-cli govern --paths a.ts b.py --title "..."   # gate an explicit change
  npx precedent-cli govern --json                # machine-readable verdict on stdout
"""
import argparse, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import govern, precedent, retrieval

VERDICT_LOG = os.path.join(govern.REPO, ".precedent", "verdicts.jsonl")
ALLOW = {"act_silently", "act_and_flag"}          # auto-merge; everything else blocks
AUTH_STATES = ["none", "precedent", "policy_match", "policy_conflict",
               "guardrail_match", "guardrail_conflict"]


def _base():
    base = os.environ.get("GATE_BASE")
    if not base and os.environ.get("GITHUB_BASE_REF"):
        base = "origin/" + os.environ["GITHUB_BASE_REF"]
    return base or "HEAD~1"


def changed_files():
    out = subprocess.check_output(["git", "diff", "--name-only", f"{_base()}...HEAD"],
                                  text=True, cwd=govern.REPO)
    return [f.strip() for f in out.splitlines() if f.strip()]


def read_diff(paths=None):
    """The actual code change — what govern should judge, not just the title. From git; '' if unavailable."""
    try:
        cmd = ["git", "diff", f"{_base()}...HEAD"] + (["--", *paths] if paths else [])
        return subprocess.check_output(cmd, text=True, cwd=govern.REPO, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def infer_action(paths):
    if any("migration" in p.lower() for p in paths):
        return "db_migration"
    return "merge"


def retrieve_candidates(query, paths, k=20):
    """Corrected retrieval (§6.2): content hybrid + soft scope, recall-additive, never prune.
    Degrades to deterministic scope+bm25 when no embedding key is available."""
    store = precedent._all_precedents()
    try:
        ids, _ = retrieval.scoped_soft(query, store, files=paths, k=k)
    except Exception:                              # no embedding key / offline -> local-only
        ids = list(set(retrieval.scope(query, store, files=paths)[0])
                   | set(retrieval.bm25(query, store, k=k)[0]))
    return [p for p in store if p["id"] in ids]


JUDGE_REPS = int(os.environ.get("GOVERN_REPS", "3"))       # self-consistency: majority over N samples


def _judge_once(query, paths, action, precs, diff=""):
    diff_block = (f"\n\nDIFF (the ACTUAL code change — judge THIS, not the title):\n{diff[:4000]}"
                  if diff and diff.strip() else "")
    prompt = (
        "You are the authority-resolution step of a coding-agent governance system. Given a "
        "proposed change and the CANDIDATE recorded decisions retrieved for it, output STRICT JSON:\n"
        '{"authority_state":"<none|precedent|policy_match|policy_conflict|guardrail_match|'
        'guardrail_conflict>","consequential":<true|false>,"applies":["<ids>"],"why":"<short>"}\n\n'
        "authority_state: the HIGHEST-authority decision whose scope covers the change "
        "(guardrail>policy>precedent). Use *_conflict ONLY when the change concretely VIOLATES the rule "
        "(does the banned thing / contradicts a superseded approach). If it complies with, or is simply "
        "governed by, the rule use *_match. When unsure between match and conflict, prefer *_match. If "
        "no decision covers the change, 'none'. When a DIFF is provided, base the match/conflict call on "
        "what the code ACTUALLY does, not what the title says.\n"
        "consequential: true only if it adds a new dependency/service/architectural pattern or is the "
        "first change in a previously-uncovered area; else false.\n\n"
        f"CHANGE: {query}\nchanged files: {paths}\naction: {action}{diff_block}\n\n"
        f"CANDIDATE DECISIONS:\n{precs}")
    out = precedent._llm(prompt, json_mode=True)
    if out:
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                if d.get("authority_state") in AUTH_STATES:
                    return (d["authority_state"], bool(d.get("consequential", False)),
                            d.get("applies", []), d.get("why", ""))
            except Exception:
                pass
    return None


PERCHECK = os.environ.get("GOVERN_PERCHECK", "0") == "1"    # per-guardrail compliance check — DEFAULT OFF.
# An adversarial review found it OVER-DENIES at scale: it checks EVERY in-scope guardrail against the diff,
# so an org-wide "must do X" rule (add tests, license header, rate-limit) fires "violates"-by-omission on
# any compliant PR that doesn't also do X -> a clean change gets denied (0%->100% false-deny as globals
# grow). Its one apparent win (E4 omission) was a single cherry-picked case that did NOT generalize
# (6/6 == 6/6 on fresh cases). Kept OFF pending a redesign: only gate on guardrails RELEVANT to the change
# (distinguish "rule not applicable" from "applicable and violated"), not every always-in-scope global.


def _check_compliance(decision, query, diff, reps):
    """Focused, per-decision check against the ACTUAL diff — catches violation-by-OMISSION (a 'must do X'
    rule is violated when the diff doesn't do X). Self-consistent (majority of `reps`)."""
    def once(_):
        out = precedent._llm(
            "Check ONE team rule against a code change. Judge the DIFF, not the title.\n"
            f"RULE ({decision['authority']}): {decision['decision']}\n"
            f"CHANGE: {query}\nDIFF:\n{diff[:4000]}\n\n"
            "Decide RELEVANCE first, then compliance:\n"
            "- 'na' if this rule does NOT govern what this change is ABOUT — a general PR-process rule "
            "(add unit tests, license header, changelog) when the change is business logic, or a rule about "
            "a different subsystem/concern than this diff touches. When unsure about relevance, answer 'na'.\n"
            "- 'violates' ONLY if the change is squarely in this rule's domain and does the wrong thing: a "
            "'never/ban X' rule and the diff does X, or a 'must do X' rule and the diff clearly omits X while "
            "doing the very operation X is required for.\n"
            "- 'complies' if it is in the rule's domain and satisfies it.\n"
            'STRICT JSON {"status":"complies|violates|na","why":"<short>"}.', json_mode=True)
        if out:
            m = re.search(r"\{.*\}", out, re.S)
            if m:
                try:
                    s = json.loads(m.group(0)).get("status")
                    if s in ("complies", "violates", "na"):
                        return s
                except Exception:
                    pass
        return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=reps) as ex:
        votes = [v for v in ex.map(once, range(reps)) if v]
    if not votes:
        return "na"
    from collections import Counter
    return Counter(votes).most_common(1)[0][0]


def _consequential(query, diff):
    out = precedent._llm(
        "Is this change CONSEQUENTIAL — introduces a new dependency/library, a new service/module, a new "
        "architectural pattern, or is the first change in a previously-uncovered area? "
        f'STRICT JSON {{"consequential":true|false}}.\nCHANGE: {query}\nDIFF:\n{diff[:2000]}', json_mode=True)
    if out:
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                return bool(json.loads(m.group(0)).get("consequential"))
            except Exception:
                pass
    return False


def _judge_percheck(query, paths, action, diff, reps):
    """Deterministic scope decides WHICH guardrails/policies apply; a focused model check decides whether
    the diff COMPLIES with each. Aggregates to an authority_state. Catches omissions the holistic call misses."""
    byid = {p["id"]: p for p in precedent._all_precedents()}
    ins = [byid[i] for i in govern.in_scope(paths) if i in byid]
    for auth, conflict, match in (("guardrail", "guardrail_conflict", "guardrail_match"),
                                  ("policy", "policy_conflict", "policy_match")):
        decs = [d for d in ins if d.get("authority") == auth]
        statuses = [(d, _check_compliance(d, query, diff, reps)) for d in decs]
        viol = [d["id"] for d, s in statuses if s == "violates"]
        comp = [d["id"] for d, s in statuses if s == "complies"]
        if viol:
            return conflict, False, viol, f"diff violates {auth}(s) {viol}"
        if comp:
            return match, False, comp, f"diff complies with {auth}(s) {comp}"
    return "none", _consequential(query, diff), [], "no guardrail/policy in scope"


def judge_authority(query, paths, action, candidates, reps=None, diff="", percheck=None):
    """The model's semantic half: over the RETRIEVED candidates only, pick the governing precedent and
    whether the change matches or conflicts — judged on the ACTUAL diff when provided (title-only is
    ambiguous: "new pricing endpoint" can't reveal whether it applies mandated audit logging). Self-
    consistency: sample `reps` times and MAJORITY-vote the authority_state (ties toward the less-
    restrictive reading to avoid over-denying). Deterministic fallback if the model is unavailable."""
    reps = reps or JUDGE_REPS
    use_pc = PERCHECK if percheck is None else percheck
    if use_pc and diff and diff.strip() and precedent._key():
        return _judge_percheck(query, paths, action, diff, reps)   # per-guardrail compliance check
    if candidates and precedent._key():
        precs = "\n".join(precedent._summary(p) for p in candidates)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=reps) as ex:
            votes = [v for v in ex.map(lambda _: _judge_once(query, paths, action, precs, diff), range(reps)) if v]
        if votes:
            from collections import Counter
            tally = Counter(v[0] for v in votes)
            top = tally.most_common(1)[0][1]
            winners = [a for a, c in tally.items() if c == top]
            # tie-break toward the least-restrictive authority_state (prefer match over conflict, none last only if alone)
            order = ["guardrail_match", "policy_match", "precedent", "policy_conflict",
                     "guardrail_conflict", "none"]
            auth = min(winners, key=lambda a: order.index(a) if a in order else 99)
            cons = sum(v[1] for v in votes) * 2 >= len(votes)      # majority-true
            rep = next(v for v in votes if v[0] == auth)
            return auth, cons, rep[2], rep[3]
    # deterministic fallback (model/key unavailable): FAIL CLOSED. We can't verify compliance, so an
    # in-scope guardrail must NOT be silently allowed — route it to a human (require_review/escalate),
    # never act_silently. (Bug fixed: this used to return guardrail_MATCH -> allowed banned changes.)
    ids = govern.in_scope(paths)
    prec = {p["id"]: p for p in precedent._all_precedents()}
    gids = [i for i in ids if prec.get(i, {}).get("authority") == "guardrail"]
    if gids:
        # policy_conflict resolves to require_review (low/med) / escalate (high) — block, human decides.
        return "policy_conflict", False, gids, "in-scope guardrail, compliance UNVERIFIED (fail-closed fallback)"
    if any(prec.get(i, {}).get("authority") == "policy" for i in ids):
        return "policy_conflict", False, ids, "in-scope policy, compliance unverified (fail-closed fallback)"
    return "none", False, ids, "no precedent in scope (deterministic fallback)"


def govern_diff(paths, title="", action=None, reps=None, diff=None, percheck=None):
    action = action or infer_action(paths)
    query = f"{title}\nfiles: {', '.join(paths)}\naction: {action}".strip()
    if diff is None:                       # judge the ACTUAL change; fall back to git if not supplied
        diff = read_diff(paths)
    candidates = retrieve_candidates(query, paths)
    authority, consequential, applies, why = judge_authority(query, paths, action, candidates,
                                                             reps=reps, diff=diff, percheck=percheck)
    risk, dims = govern.derive_risk(paths, action)
    verdict = govern.resolve(authority, risk, consequential)
    return {
        "verdict": verdict,
        "allow": verdict in ALLOW,
        "authority_state": authority,
        "consequential": consequential,
        "risk_tier": risk,
        "dimensions": {k: v for k, v in dims.items()},
        "precedent_ids": applies,
        "candidate_ids": [c["id"] for c in candidates],
        "why": why,
        "paths": paths,
        "action": action,
        "title": title,
    }


VERDICT_LINE = {
    "act_silently":   "✅ ALLOW — auto-merge (silent, within policy)",
    "act_and_flag":   "✅ ALLOW — auto-merge, flagged for visibility",
    "require_review":  "🟡 BLOCK — human review required",
    "escalate":        "🟠 BLOCK — escalate: a human must decide (and this becomes a precedent)",
    "deny":            "⛔ BLOCK — denied: violates a guardrail",
}


def render(v):
    L = ["## 🔐 Precedent — autonomy verdict", "",
         f"**{VERDICT_LINE.get(v['verdict'], v['verdict'])}**", "",
         f"- **changed files:** {', '.join(v['paths']) or '(none)'}",
         f"- **action:** `{v['action']}`  •  **risk tier:** `{v['risk_tier']}`"
         f"  •  **consequential:** {'yes' if v['consequential'] else 'no'}",
         f"- **authority:** `{v['authority_state']}`"
         + (f"  •  **governing precedent(s):** {', '.join(v['precedent_ids'])}" if v['precedent_ids'] else ""),
         f"- **candidates retrieved:** {len(v['candidate_ids'])}"
         + (f" ({', '.join(v['candidate_ids'])})" if v['candidate_ids'] else ""),
         f"- **why:** {v['why'] or '—'}"]
    rec = (f'npx precedent-cli record "situation: {v["title"] or "this change"}; '
           f'decided <X>; because <reason>; scope {" ".join(v["paths"]) or "<paths>"}"')
    if not v["allow"]:
        L += ["", "### Why blocked / what's needed",
              "This change touches governed territory. To proceed, the required authority must "
              "approve **and record the reason** so the next agent inherits the decision:",
              "", "```", rec, "```"]
    elif v["authority_state"] == "none":
        # allowed but NO precedent governed it (consequential+none escalates above, so this is the
        # lower-stakes no-precedent case). Light, non-blocking nudge: if it set a pattern, record it.
        L += ["", "_📝 No precedent governed this. If it establishes a pattern others should follow "
              "(a reuse/canonical-source choice, a new convention), record it so the next agent inherits it:_",
              "```", rec, "```"]
    return "\n".join(L)


def _next_verdict_id():
    n = 0
    if os.path.exists(VERDICT_LOG):
        n = sum(1 for _ in open(VERDICT_LOG))
    return f"V-{n + 1:04d}"


def log_verdict(v, pr=None):
    """Append the verdict and return its stable id (so an outcome can join to it later)."""
    vid = _next_verdict_id()
    rec = {"id": vid, "ts": int(time.time()), "pr": pr,
           **{k: v[k] for k in ("verdict", "allow", "authority_state", "risk_tier",
              "consequential", "precedent_ids", "paths", "action", "title")}}
    with open(VERDICT_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return vid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", nargs="*", help="changed files (default: git diff vs base)")
    ap.add_argument("--title", default="", help="PR title / change description")
    ap.add_argument("--action", default=None)
    ap.add_argument("--pr", default=None, help="PR number/URL to key the outcome to")
    ap.add_argument("--diff", default=None, help="path to a diff/patch file, or '-' for stdin "
                    "(default: read git diff vs base). Govern judges the ACTUAL code, not just the title.")
    ap.add_argument("--json", action="store_true", help="emit JSON verdict only")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args()
    paths = a.paths if a.paths is not None else changed_files()
    diff = None
    if a.diff == "-":
        diff = sys.stdin.read()
    elif a.diff:
        diff = open(a.diff).read()
    v = govern_diff(paths, a.title, a.action, diff=diff)
    vid = None
    if not a.no_log:
        vid = log_verdict(v, pr=a.pr)
        v["id"] = vid
    if a.json:
        print(json.dumps(v, indent=2))
    else:
        print(render(v))
        if vid:
            print(f"\n_verdict id: {vid}_ — when this PR resolves, capture the outcome:\n"
                  f"  npx precedent-cli outcome label {vid} <merged_clean|reverted|blocked_upheld|"
                  f"blocked_overridden> --applied <ids> --reason \"...\"")
    sys.exit(0 if v["allow"] else 1)


if __name__ == "__main__":
    main()
