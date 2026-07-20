#!/usr/bin/env python3
"""Precedent service — the harness side of the loop. A coding agent calls this.

Two directions:

  npx precedent-cli retrieve "<what I'm about to decide + files involved>"
      -> a decision packet: the org's recorded decisions that apply, their authority,
         why they apply, a recommendation, and an escalate-if condition.

  npx precedent-cli record "<free text: situation; decided X; because Y; scope paths>"
      -> structures the note into a decision episode and appends it to the store as
         'unconfirmed' (admission control: agent-captured decisions never enter as
         policy/guardrail until a human promotes them).

Uses the model (OpenRouter, ARM_MODEL) when a key is available (env OPENROUTER_API_KEY
or .precedent/.env); degrades to keyword retrieval / raw capture otherwise.
"""
import json, os, re, sys, urllib.request
import govern

CAPTURED = os.path.join(govern.REPO, ".precedent", "captured.json")
EVENTS = os.path.join(govern.REPO, ".precedent", "events.jsonl")
_STOP = set("the a an of to and or in on for with by is are be am was were as at from into this that it what should must do does did how can could would will not no new add set get use using used all any each per via you we i my our your their has have had they them then than so if but".split())
MODEL = os.environ.get("ARM_MODEL", "deepseek/deepseek-v4-flash")


def _decision_hash(d):
    """Content hash of a decision — anchors its text/authority/scope in the ledger (tamper-evidence)."""
    import hashlib
    key = json.dumps({"id": d.get("id"), "decision": d.get("decision", ""),
                      "authority": d.get("authority", ""),
                      "scope": d.get("scope", {}).get("paths", d.get("scope_paths", []))}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()

def _last_event_hash():
    if not os.path.exists(EVENTS):
        return "genesis"
    last = ""
    with open(EVENTS) as f:
        for line in f:
            if line.strip():
                last = line
    try:
        return json.loads(last).get("hash", "genesis") if last else "genesis"
    except Exception:
        return "genesis"

def _log_event(kind, **kw):
    """Append a HASH-CHAINED event: a live session's behavior is measurable (flywheel metric) AND the
    ledger is tamper-evident — each entry seals the previous one, so an edited/removed/reordered event
    breaks the chain (see verify.py)."""
    try:
        import hashlib, time as _t
        prev = _last_event_hash()
        ev = {"ts": int(_t.time()), "kind": kind, **kw, "prev": prev}
        ev["hash"] = hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()
        with open(EVENTS, "a") as f:
            f.write(json.dumps(ev) + "\n")
    except Exception:
        pass

def _key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k
    envf = os.path.join(govern.REPO, ".precedent", ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None

def _llm(prompt, max_tokens=2500, json_mode=True):
    # DeepSeek V4 Flash reasons before answering; too small a budget yields empty content
    # (finish=length). Give room + force JSON, and retry on both errors and empty content.
    key = _key()
    if not key:
        return None
    payload = {"model": MODEL, "temperature": 0, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode()
    for attempt in range(3):
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            content = r["choices"][0]["message"].get("content") or ""
            if content.strip():              # empty = reasoning ate the budget -> retry
                return content
        except Exception:
            pass
    return None

def _all_precedents():
    store = list(govern.DECISIONS)                         # already active-filtered by govern
    if os.path.exists(CAPTURED):
        store += [p for p in json.load(open(CAPTURED)).get("precedents", []) if govern.is_active(p)]
    return store

def _summary(p):
    paths = p.get("scope", {}).get("paths", p.get("scope_paths", []))
    return f'{p["id"]} [{p["authority"]}] scope={paths}: {p["decision"]} — {p.get("reasoning","")}'

# ---------- retrieve ----------
def retrieve_packet(query):
    """Return the decision-packet dict for a situation. Reused by CLI and MCP server.

    Retrieval is LOCAL — bm25 + local embeddings + scope (the same hot-path strategy the product uses
    at scale), NO big reasoning-model call. Embeddings are a small local model, not a reasoning LLM. The
    packet content is VERBATIM from the store (decision text + recorded reasoning) and the recommendation
    is DETERMINISTIC — we never let a model synthesize prescriptive advice (a paraphrase can drift and
    contradict the decision it cites: observed a retrieve that recommended a per-channel retry class, the
    exact anti-pattern the retrieved decision forbids). Surface the fact; let the agent reason."""
    precs = _all_precedents()
    byid = {p["id"]: p for p in precs}
    import retrieval                     # lazy (retrieval imports precedent)
    # SEMANTIC rank + ABSTENTION: rank decisions by cosine of the query to the decision embedding and
    # keep only those above a floor. Measured on the scaled adversarial benchmark, cosine ranking gives
    # recall@1 ~91% vs ~60% for the old bm25 re-rank — bm25 floored out low-lexical-overlap paraphrases
    # and admitted common-word near-misses. When nothing clears the floor the packet emits the
    # "open question — record it" path instead of attaching a stray decision.
    # Floor tuned on a held-out set (src/eval_retrieval_scale.py): at 0.44 held-out recall@1 was only
    # 61% (abstention 89%); 0.40 lifts recall to 83% (balanced 69%->78%) while ALL pure-negative queries
    # still abstain (only adjacent near-misses cross over). A path-scope bonus was tried and measured
    # NET-NEGATIVE — agents name the file in the query, so the embedding already captures the path signal;
    # the bonus added no recall and created false positives on off-topic in-scope changes. So: floor only.
    COS_FLOOR = float(os.environ.get("PRECEDENT_RETRIEVE_FLOOR", "0.40"))
    try:
        sims = retrieval.vector_scores(query, precs)
        ids = [i for i in sorted(sims, key=lambda i: -sims[i]) if sims[i] > COS_FLOOR][:6]
    except Exception:                   # offline / no embedding key -> pure-lexical bm25 fallback
        _clean = " ".join(t for t in retrieval._tok(query) if t not in _STOP and len(t) > 2)
        _bm = retrieval.BM25([retrieval._dtext(p) for p in precs])
        _sc = {p["id"]: s for p, s in zip(precs, _bm.scores(_clean))}
        ids = sorted((i for i in _sc if _sc[i] > 0.5), key=lambda i: -_sc[i])[:6]
    # build the packet from VERBATIM store data — no model synthesis
    rel = [{"id": i, "authority": byid[i]["authority"], "decision": byid[i]["decision"],
            "reasoning": byid[i].get("reasoning", "")} for i in ids]
    has_guard = any(r["authority"] == "guardrail" for r in rel)
    rec = ("Follow the decisions above; guardrail-authority ones override your own judgment"
           + (" — a conflict with a guardrail is blocked at the merge gate." if has_guard else ".")) \
        if rel else "No recorded decision applies — you are making a NEW decision. Decide, then record it."
    data = {"relevant": rel, "recommendation": rec,
            "escalate_if": "the action is irreversible (prod/money/deletes/migration) or conflicts with a guardrail"}
    _log_event("retrieve", query=query[:140], returned=ids)
    return data

def format_packet(query, data):
    lines = ["── Precedent decision packet ──────────────────", f" situation: {query[:80]}"]
    rel = data.get("relevant", [])
    if not rel:
        lines += [" no recorded decision applies — this is an OPEN QUESTION.",
                  " → decide, then RECORD it so the next agent inherits it."]
    for r in rel:
        lines.append(f" • {r.get('id')} [{r.get('authority')}] {r.get('decision','')}")
        if r.get("reasoning"):
            lines.append(f"     why: {r['reasoning']}")
    if data.get("recommendation"):
        lines.append(f" recommendation: {data['recommendation']}")
    if data.get("escalate_if"):
        lines.append(f" escalate if: {data['escalate_if']}")
    lines.append("───────────────────────────────────────────────")
    return "\n".join(lines)

def retrieve(query):
    print(format_packet(query, retrieve_packet(query)))

# ---------- record ----------
def record_episode(note, deny=None):
    """Structure a free-text note into a decision episode, store it, return it.
    `deny` = optional list of regexes; once this decision is promoted to a guardrail, a match on a
    change's added diff lines is a deterministic, injection-proof block (see govern_cli/judge_authority)."""
    prompt = ("Extract a structured decision episode from this engineer's note. "
              "Output STRICT JSON only, no prose:\n"
              '{"situation":"..","decision":"..","reasoning":"..","scope_paths":[".."],"evidence":[".."]}\n\n'
              f"NOTE:\n{note}")
    out = _llm(prompt)
    ep = None
    if out:
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                ep = json.loads(m.group(0))
            except Exception:
                ep = None
    if ep is None:  # raw fallback — never lose the capture
        ep = {"situation": note, "decision": note, "reasoning": "", "scope_paths": [], "evidence": []}
    # the LLM can return valid JSON missing some keys — never let a partial parse crash record()
    for k, dv in (("situation", note), ("decision", note), ("reasoning", ""), ("scope_paths", []), ("evidence", [])):
        ep.setdefault(k, dv)
    ep["authority"] = "unconfirmed"      # admission control (PRD §4.5)
    ep["source"] = "agent-capture"
    if deny:
        ep["deny_patterns"] = deny if isinstance(deny, list) else [deny]
    try:                                 # record-time enrichment: makes it findable by triggering
        import enrich                    # situations (validated +4-5pts recall @tight budget). Off hot path.
        ep["enrichment"] = enrich.enrich_decision(ep["decision"], ep.get("reasoning", ""))
    except Exception:
        pass
    store = {"precedents": []}
    if os.path.exists(CAPTURED):
        store = json.load(open(CAPTURED))
    ep["id"] = f"C-{len(store['precedents']) + 1:03d}"
    store["precedents"].append(ep)
    with open(CAPTURED, "w") as f:
        json.dump(store, f, indent=2)
    _log_event("record", id=ep["id"], decision=ep["decision"][:140], content_hash=_decision_hash(ep))
    return ep

def record(note, deny=None):
    ep = record_episode(note, deny=deny)
    print(f"✓ recorded {ep['id']} (authority: UNCONFIRMED — a human must promote it to policy/guardrail)")
    if deny:
        print(f"  deny_patterns attached: {ep['deny_patterns']} — a deterministic, injection-proof block once promoted to guardrail")
    print(json.dumps(ep, indent=2))

DECISIONS_FILE = os.path.join(govern.REPO, ".precedent", "decisions.json")

def _find_and_update(dec_id, mutate):
    """Find a decision by id across the captured + committed stores, apply mutate(d), persist."""
    for path in (CAPTURED, DECISIONS_FILE):
        if not os.path.exists(path):
            continue
        store = json.load(open(path))
        precs = store.get("precedents", store) if isinstance(store, dict) else store
        for d in precs:
            if isinstance(d, dict) and d.get("id") == dec_id:
                mutate(d)
                with open(path, "w") as f:
                    json.dump(store, f, indent=2)
                return os.path.basename(path)
    return None

def deprecate(dec_id, reason="", superseded_by=None, revoke=False, propose=False, actor="human"):
    """Retire a decision. Human applies immediately; agent (--propose) only PROPOSES — the decision
    stays active + flagged until `confirm-deprecation` (admission control, mirrors record/promote)."""
    import datetime
    status = ("proposed_deprecation" if propose else "revoked" if revoke
              else "superseded" if superseded_by else "deprecated")
    meta = {"by": actor, "reason": reason, "at": datetime.datetime.now().isoformat(timespec="seconds")}
    if superseded_by:
        meta["superseded_by"] = superseded_by
    where = _find_and_update(dec_id, lambda d: d.update({"status": status, "deprecation": meta}))
    if not where:
        print(f"decision {dec_id} not found"); return
    _log_event("deprecate", id=dec_id, status=status, actor=actor)
    if propose:
        print(f"⚠ {dec_id}: deprecation PROPOSED by {actor} — still active until a human runs "
              f"`npx precedent-cli confirm-deprecation {dec_id}`. reason: {reason or '(none)'}")
    else:
        print(f"✓ {dec_id} → {status}" + (f" (superseded by {superseded_by})" if superseded_by else "")
              + " — it will no longer be retrieved or enforced.")

def confirm_deprecation(dec_id):
    import datetime
    def m(d):
        prev = d.get("deprecation", {})
        d["status"] = "superseded" if prev.get("superseded_by") else "deprecated"
        prev.update({"confirmed_by": "human", "confirmed_at": datetime.datetime.now().isoformat(timespec="seconds")})
        d["deprecation"] = prev
    if not _find_and_update(dec_id, m):
        print(f"decision {dec_id} not found"); return
    _log_event("confirm_deprecation", id=dec_id)
    print(f"✓ {dec_id} deprecation confirmed — no longer retrieved or enforced.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    a = sys.argv[2:]
    def _opt(f):
        return a[a.index(f) + 1] if f in a and a.index(f) + 1 < len(a) else None
    if cmd == "retrieve" and a:
        retrieve(a[0])
    elif cmd == "record" and a:
        deny, note, i = [], None, 0
        while i < len(a):
            if a[i] == "--deny" and i + 1 < len(a):
                deny.append(a[i + 1]); i += 2
            else:
                note = note or a[i]; i += 1
        record(note or "", deny=deny or None)
    elif cmd == "deprecate" and a:
        # FAIL-SAFE: default is PROPOSE. Retiring a decision (esp. a guardrail) needs explicit human
        # intent via --apply, so a shell-capable agent can't silently disable enforcement.
        apply = "--apply" in a
        deprecate(a[0], reason=_opt("--reason") or "", superseded_by=_opt("--superseded-by"),
                  revoke="--revoke" in a, propose=not apply,
                  actor=_opt("--actor") or ("human" if apply else "agent"))
    elif cmd == "confirm-deprecation" and a:
        confirm_deprecation(a[0])
    else:
        print('usage: npx precedent-cli retrieve|record "<text>"\n'
              '       npx precedent-cli deprecate <id> [--reason R] [--superseded-by ID] [--revoke]   # proposes (safe default)\n'
              '       npx precedent-cli deprecate <id> --apply   # human: retire immediately\n'
              '       npx precedent-cli confirm-deprecation <id>  # human: confirm an agent/detector proposal')
        sys.exit(2)
