#!/usr/bin/env python3
"""Pluggable retrieval strategies for candidate generation.

Each strategy: retrieve(query, decisions, **kw) -> (ids, latency_seconds).
The point is to A/B them on recall vs latency (see dcbench/retrieval_eval.py),
because the DCBench run proved retrieval RECALL is the compliance ceiling.

  full_llm   : ask the model which decisions apply, over ALL decisions (current; slow, high recall)
  scope      : deterministic path-glob on the touched files (0 model calls; only for path-scoped decisions)
  bm25       : pure-Python BM25 keyword retrieval, top-k (0 model calls, <1ms, local)
  bm25_rerank: bm25 candidates -> a model filters for applicability (hand a SMALL set to a model)

'scope' and 'bm25' need no model and run locally in ~microseconds–ms — the hot-path options.
"""
import json, math, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import precedent

def _tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())

# ---------------- BM25 (pure python) ----------------
class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = [_tok(d) for d in docs]
        self.N = len(self.docs)
        self.avgdl = (sum(len(d) for d in self.docs) / self.N) if self.N else 0
        self.df = {}
        for d in self.docs:
            for w in set(d):
                self.df[w] = self.df.get(w, 0) + 1
        self.k1, self.b = k1, b

    def _idf(self, w):
        n = self.df.get(w, 0)
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1)

    def scores(self, query):
        qt = _tok(query)
        out = []
        for d in self.docs:
            dl = len(d)
            tf = {}
            for w in d:
                tf[w] = tf.get(w, 0) + 1
            s = 0.0
            for w in qt:
                f = tf.get(w, 0)
                if f:
                    s += self._idf(w) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out

def _dtext(d):
    base = d["decision"] + " " + d.get("reasoning", "") + " " + d.get("category", "")
    e = d.get("enrichment")          # record-time enrichment (triggers/anti-pattern/keywords) — see tools/enrich.py
    if e:
        base += " " + " ".join(e.get("triggers", [])) + " " + e.get("anti_pattern", "") \
                + " " + " ".join(e.get("keywords", []))
    return base

# ---------------- HyPE / doc2query expansion (offline recall booster) ----------------
_HYPE = None

def _hype():
    """Lazy-load doc-side hypothetical task phrasings: {decision_id: [phrasing, ...]}."""
    global _HYPE
    if _HYPE is None:
        p = os.path.join(os.path.dirname(__file__), "extract", "real_decisions_hype.json")
        _HYPE = json.load(open(p)) if os.path.exists(p) else {}
    return _HYPE

def _dtext_hype(d):
    return _dtext(d) + " " + " ".join(_hype().get(d["id"], []))

# ---------------- strategies ----------------
def _gmatch(cp, glob):
    return cp.startswith(glob[:-2]) if glob.endswith("**") else cp == glob

def scope(query, decisions, files=None, **_):
    """RECALL-SAFE scope prefilter: a decision survives if it's unscoped/global (NEVER dropped)
    OR its scope.paths glob-matches any touched file. Deterministic, <1ms, model-free."""
    t = time.time()
    files = files or []
    ids = []
    for d in decisions:
        paths = d.get("scope", {}).get("paths", [])
        if not paths or any(_gmatch(cp, g) for cp in files for g in paths):
            ids.append(d["id"])            # global always survives; scoped survives on path match
    return ids, time.time() - t

def scoped_hybrid(query, decisions, files=None, k=20, **_):
    """HARD scope prefilter -> deep union. NOTE: real-data eval showed this HURTS recall
    (applicable decisions cross scope boundaries). Kept for the record; prefer scoped_soft."""
    t = time.time()
    pool_ids = set(scope(query, decisions, files=files)[0])
    pool = [d for d in decisions if d["id"] in pool_ids]
    if len(pool) < 3:
        pool = decisions
    ids = set(bm25(query, pool, k=k)[0]) | set(vector(query, pool, k=k)[0])
    return list(ids), time.time() - t

def scope_matched(query, decisions, files=None, **_):
    """ONLY decisions whose scope.paths glob-matches a touched file (excludes globals)."""
    t = time.time()
    files = files or []
    ids = [d["id"] for d in decisions
           if d.get("scope", {}).get("paths") and any(_gmatch(cp, g) for cp in files for g in d["scope"]["paths"])]
    return ids, time.time() - t

def scoped_soft(query, decisions, files=None, k=20, **_):
    """The CORRECTED design: content hybrid over the full store, UNION the scope-matched decisions.
    Recall-additive (a superset of hybrid) — scope helps, never prunes true decisions."""
    t = time.time()
    ids = set(hybrid(query, decisions, k=k)[0]) | set(scope_matched(query, decisions, files=files)[0])
    return list(ids), time.time() - t

def bm25(query, decisions, k=4, **_):
    t = time.time()
    bm = BM25([_dtext(d) for d in decisions])
    sc = bm.scores(query)
    ranked = sorted(range(len(decisions)), key=lambda i: -sc[i])
    ids = [decisions[i]["id"] for i in ranked[:k] if sc[i] > 0]
    return ids, time.time() - t

def full_llm(query, decisions, **_):
    t = time.time()
    summ = "\n".join(f'{d["id"]}: {d["decision"]}' for d in decisions)
    out = precedent._llm('Return STRICT JSON {"relevant":[{"id":".."}]} listing ONLY the recorded '
                         f"decisions that apply to this task.\n\nTASK: {query}\n\nDECISIONS:\n{summ}",
                         json_mode=True)
    return _parse_ids(out, decisions), time.time() - t

def bm25_rerank(query, decisions, k=6, **_):
    t = time.time()
    cand_ids, _ = bm25(query, decisions, k=k)
    cands = [d for d in decisions if d["id"] in cand_ids]
    if not cands:
        return [], time.time() - t
    summ = "\n".join(f'{d["id"]}: {d["decision"]}' for d in cands)
    out = precedent._llm('From these CANDIDATE decisions return STRICT JSON {"relevant":[{"id":".."}]} '
                         f"for ONLY those that apply to the task.\n\nTASK: {query}\n\nCANDIDATES:\n{summ}",
                         json_mode=True)
    return _parse_ids(out, cands), time.time() - t

# ---------------- vector (embeddings) ----------------
# Uses OpenRouter's embedding endpoint as a stand-in for a small LOCAL embedding model
# (a local model gives comparable recall at local latency — no big-model reasoning call).
_EMB_CACHE = {}

def _embed(texts):
    key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("EMB_MODEL", "openai/text-embedding-3-small")
    vecs = []
    for i in range(0, len(texts), 100):                # batch for large corpora
        body = json.dumps({"model": model, "input": texts[i:i + 100]}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/embeddings", data=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=90))
        vecs += [d["embedding"] for d in r["data"]]
    return vecs

def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)

def vector(query, decisions, k=6, **_):
    t = time.time()
    ck = tuple(d["id"] for d in decisions)
    if ck not in _EMB_CACHE:                      # decision embeddings computed once (offline in prod)
        _EMB_CACHE[ck] = _embed([_dtext(d) for d in decisions])
    dvecs = _EMB_CACHE[ck]
    qv = _embed([query])[0]
    sims = [_cos(qv, dv) for dv in dvecs]
    ranked = sorted(range(len(decisions)), key=lambda i: -sims[i])
    return [decisions[i]["id"] for i in ranked[:k]], time.time() - t

def vector_scores(query, decisions):
    """{id: cosine} for every decision (cached decision embeddings). Used for semantic
    ranking + abstention in the packet — the semantic signal BM25 alone throws away."""
    ck = tuple(d["id"] for d in decisions)
    if ck not in _EMB_CACHE:
        _EMB_CACHE[ck] = _embed([_dtext(d) for d in decisions])
    qv = _embed([query])[0]
    return {d["id"]: _cos(qv, dv) for d, dv in zip(decisions, _EMB_CACHE[ck])}

def hybrid(query, decisions, k=6, files=None, **_):
    """Union of the model-free candidate generators: scope (exact) + bm25 (lexical) + vector (semantic)."""
    t = time.time()
    ids = set()
    ids |= set(scope(query, decisions, files=files)[0])
    ids |= set(bm25(query, decisions, k=k)[0])
    ids |= set(vector(query, decisions, k=k)[0])
    return list(ids), time.time() - t

# ---------------- HyPE-aware strategies (index the hypothetical phrasings too) ----------------
def hype_bm25(query, decisions, k=6, **_):
    """BM25 over decision text EXPANDED with its hypothetical task phrasings."""
    t = time.time()
    bm = BM25([_dtext_hype(d) for d in decisions])
    sc = bm.scores(query)
    ranked = sorted(range(len(decisions)), key=lambda i: -sc[i])
    ids = [decisions[i]["id"] for i in ranked[:k] if sc[i] > 0]
    return ids, time.time() - t

_HYPE_EMB_CACHE = {}

def hype_vector(query, decisions, k=6, **_):
    """Multi-vector semantic: each decision is represented by its own text + each hypothetical
    phrasing; a decision's score is the MAX cosine over its variants (max-pooling)."""
    t = time.time()
    ck = ("hype",) + tuple(d["id"] for d in decisions)
    if ck not in _HYPE_EMB_CACHE:
        texts, owner = [], []
        for i, d in enumerate(decisions):
            for v in [_dtext(d)] + _hype().get(d["id"], []):
                texts.append(v); owner.append(i)
        _HYPE_EMB_CACHE[ck] = (_embed(texts), owner)   # computed once (offline in prod)
    vecs, owner = _HYPE_EMB_CACHE[ck]
    qv = _embed([query])[0]
    best = [-1e9] * len(decisions)
    for v, o in zip(vecs, owner):
        s = _cos(qv, v)
        if s > best[o]:
            best[o] = s
    ranked = sorted(range(len(decisions)), key=lambda i: -best[i])
    return [decisions[i]["id"] for i in ranked[:k]], time.time() - t

def hype_hybrid(query, decisions, k=6, files=None, **_):
    """Content hybrid with HyPE-expanded lexical + semantic sides."""
    t = time.time()
    ids = set()
    ids |= set(scope(query, decisions, files=files)[0])
    ids |= set(hype_bm25(query, decisions, k=k)[0])
    ids |= set(hype_vector(query, decisions, k=k)[0])
    return list(ids), time.time() - t

def scoped_soft_hype(query, decisions, files=None, k=20, **_):
    """The recall-max hot-path candidate: HyPE content hybrid UNION scope-matched (additive, never prunes)."""
    t = time.time()
    ids = set(hype_hybrid(query, decisions, k=k)[0]) | set(scope_matched(query, decisions, files=files)[0])
    return list(ids), time.time() - t

# ---------------- HONEST strategies (no unconditional global dump) ----------------
# The adversarial review (2026-07-17) showed scope() unconditionally returns ALL global
# (unscoped) decisions, and every "hybrid"/"scoped_soft" strategy unions it in. On real data
# that was 294/1,140 decisions injected free every query, guaranteeing any global GT is a "hit"
# and inflating recall ~16 pts. These variants DO NOT special-case globals: globals compete on
# content like everything else, and scope adds only PATH-MATCHED decisions (a real, task-specific
# signal). This is the honest recall the product actually earns.
def content_hybrid(query, decisions, k=6, **_):
    """bm25 (lexical) ∪ vector (semantic). No scope, no global dump — pure content retrieval."""
    t = time.time()
    ids = set(bm25(query, decisions, k=k)[0]) | set(vector(query, decisions, k=k)[0])
    return list(ids), time.time() - t

def soft(query, decisions, files=None, k=6, **_):
    """content_hybrid ∪ scope-MATCHED (path-matched only). The honest soft-scope design."""
    t = time.time()
    ids = set(content_hybrid(query, decisions, k=k)[0]) | set(scope_matched(query, decisions, files=files)[0])
    return list(ids), time.time() - t

def content_hype(query, decisions, k=6, **_):
    """HyPE-expanded content hybrid, no global dump."""
    t = time.time()
    ids = set(hype_bm25(query, decisions, k=k)[0]) | set(hype_vector(query, decisions, k=k)[0])
    return list(ids), time.time() - t

def soft_hype(query, decisions, files=None, k=6, **_):
    """content_hype ∪ scope-MATCHED. The honest recall-max hot-path candidate."""
    t = time.time()
    ids = set(content_hype(query, decisions, k=k)[0]) | set(scope_matched(query, decisions, files=files)[0])
    return list(ids), time.time() - t

def _parse_ids(out, decisions):
    valid = {d["id"] for d in decisions}
    if not out:
        return []
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return []
    try:
        return [r["id"] for r in json.loads(m.group(0)).get("relevant", []) if r.get("id") in valid]
    except Exception:
        return []

STRATEGIES = {"scope": scope, "scope_matched": scope_matched, "scoped_hybrid": scoped_hybrid,
              "scoped_soft": scoped_soft, "bm25": bm25, "vector": vector, "hybrid": hybrid,
              "hype_bm25": hype_bm25, "hype_vector": hype_vector, "hype_hybrid": hype_hybrid,
              "scoped_soft_hype": scoped_soft_hype,
              "content_hybrid": content_hybrid, "soft": soft,
              "content_hype": content_hype, "soft_hype": soft_hype,
              "full_llm": full_llm, "bm25_rerank": bm25_rerank}
