#!/usr/bin/env python3
"""Scaled stress test for semantic dedup — why it's OPT-IN, not default.

Generates ~700 structurally-distinct engineering rules (enumerated domain×subject×predicate×qual)
plus 200 injected paraphrase groups (base + 2 restatements = known dupes), then sweeps the cosine
threshold and reports, at scale, dupe-collapse recall vs false-merge (distinct rules wrongly merged).

Finding (the reason semantic dedup ships OFF by default): there is NO safe threshold — where it
catches dupes (0.65-0.80) it false-merges 30-70% of DISTINCT rules (greedy chaining), and where
false-merge is low (0.88+) dupe-recall collapses to ~0. A fixed cosine threshold silently deletes
real decisions at scale. The exact-text dedup (safe) is the default; this documents why.

  OPENROUTER_API_KEY=... python3 src/eval_dedup_scale.py
"""
import os, sys, math, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import retrieval
random.seed(7)

DOMAINS = {
 "caching": (["the response cache","the session store","the query cache","API responses","computed aggregates","the CDN layer","rate-limit counters","feature-flag reads"],
             ["must set an explicit TTL","must use Redis, not a local map","must be invalidated on every write","must never hold PII","must be namespaced per tenant","must fall back gracefully on a miss","must be size-bounded"]),
 "auth": (["access tokens","refresh tokens","admin sessions","service accounts","password resets","API keys","OAuth callbacks","MFA enrollment"],
          ["must expire within 15 minutes","must be rotated on each use","must require multi-factor auth","must never store PII in the payload","must be revocable server-side","must be rate-limited","must be scoped to least privilege"]),
 "api": (["list endpoints","public endpoints","error responses","write endpoints","the version prefix","deprecated routes","webhook payloads","bulk operations"],
         ["must be paginated","must be versioned in the URL path","must return problem+json","must be idempotent","must validate input with a schema","must document a deprecation window","must enforce a request size limit"]),
 "database": (["schema migrations","destructive changes","long transactions","foreign keys","indexes","connection pools","read replicas","backups"],
              ["must be backward-compatible for one deploy","must run inside a single transaction","must use optimistic locking","must not drop columns still written","must be reviewed before merge","must have a bounded timeout","must be tested in CI"]),
 "logging": (["application logs","audit logs","error logs","request traces","debug output","metrics emission","log retention","structured fields"],
             ["must be structured JSON","must include a request_id","must never contain secrets","must never contain PII","must use the shared logger","must be sampled under load","must set a retention window"]),
 "errors": (["external calls","empty catch blocks","retries","timeouts","circuit breakers","error types","panics","fallbacks"],
            ["must never be swallowed silently","must be wrapped with a timeout","must use bounded exponential backoff","must return a typed error","must be logged with context","must not leak internal details","must degrade gracefully"]),
 "payments": (["provider charges","card data","refunds","the ledger","webhooks","payouts","currency conversion","disputes"],
              ["must include an idempotency key","must never store the raw PAN","must be reconciled daily","must be double-entry","must verify the signature","must be audited","must round using bankers rounding"]),
 "security": (["secrets","PII at rest","user input","dependencies","TLS","CORS","file uploads","session cookies"],
              ["must come from the vault","must be encrypted","must be sanitized","must be pinned to a version","must enforce TLS 1.2+","must use an allow-list of origins","must be virus-scanned","must set Secure and HttpOnly flags"]),
 "testing": (["new endpoints","service code","critical paths","flaky tests","fixtures","mocks","coverage","load tests"],
             ["must ship with integration tests","must keep 80% coverage","must be deterministic","must not hit the network","must be quarantined when flaky","must assert on behavior","must run in CI before merge"]),
 "frontend": (["styling","server state","client state","forms","images","routing","the bundle","accessibility"],
              ["must use Tailwind not styled-components","must use React Query not Redux","must be code-split","must be lazy-loaded","must meet WCAG AA","must validate on client and server","must be memoized when expensive"]),
 "deploy": (["release branches","feature rollout","migrations","config changes","rollbacks","canaries","secret rotation","blue-green cutover"],
            ["must prefer feature flags","must be reversible in one step","must run behind a canary","must not require downtime","must be gated by a health check","must be announced in the release channel","must be idempotent"]),
 "deps": (["third-party packages","transitive deps","version ranges","licenses","native modules","dev dependencies","lockfiles","upgrades"],
          ["must be pinned exactly","must be approved by a reviewer","must pass a license check","must be scanned for CVEs","must be committed to the lockfile","must be removed when unused","must be updated on a schedule"]),
 "concurrency": (["shared state","multi-step writes","background jobs","queues","distributed locks","idempotency keys","message ordering","batching"],
                 ["must run in a transaction","must be idempotent","must use optimistic locking","must have a dead-letter queue","must bound the retry count","must not block the event loop","must be at-least-once safe"]),
 "config": (["secrets","environment flags","default values","feature flags","timeouts","limits","service URLs","credentials"],
            ["must not be committed to the repo","must have a safe default","must be validated at startup","must be overridable per environment","must be documented","must be typed","must fail closed"]),
 "monitoring": (["SLOs","alerts","dashboards","health checks","distributed tracing","error budgets","on-call rotation","incident reviews"],
                ["must have a defined target","must be actionable not noisy","must page on customer impact","must expose a healthz endpoint","must propagate a trace id","must be reviewed weekly","must have a runbook"]),
}
QUALS = ["", " in production", " for all new code", " across services", " before deploy"]

def build():
    seen, bases = set(), []
    for subs, preds in DOMAINS.values():
        for s in subs:
            for p in preds:
                for q in QUALS:
                    t = f"{s.capitalize()} {p}{q}."
                    if t not in seen:
                        seen.add(t); bases.append(t)
    random.shuffle(bases); bases = bases[:700]
    def para(r):
        x = r.rstrip(".").replace(" must ", " is required to ").replace(" never ", " not ever ")
        return ("Always ensure that " + x[0].lower() + x[1:] if random.random() < .5 else x) + "."
    def para2(r):
        return "Team rule: " + r.rstrip(".").replace(" must ", " must, without exception, ")[0].lower() + r.rstrip(".").replace(" must ", " must, without exception, ")[1:] + "."
    items = []
    for i, b in enumerate(bases):
        items.append({"text": b, "group": i if i < 200 else -1})
        if i < 200:
            items += [{"text": para(b), "group": i}, {"text": para2(b), "group": i}]
    random.shuffle(items)
    return items, bases

def main():
    items, bases = build()
    print(f"corpus: {len(items)} items | {len(bases)} distinct bases + 200 paraphrase groups\n")
    vecs = retrieval._embed([it["text"] for it in items])
    def nrm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    vecs = [nrm(v) for v in vecs]
    from collections import defaultdict
    gm = defaultdict(list)
    for i, it in enumerate(items):
        if it["group"] >= 0: gm[it["group"]].append(i)
    singles = [i for i, it in enumerate(items) if it["group"] == -1]

    def dedup(sim):
        ki, kv, merged = [], [], {}
        for i, v in enumerate(vecs):
            hit = None
            for cv, ci in zip(kv, ki):
                if sum(a * b for a, b in zip(v, cv)) >= sim:
                    hit = ci; break
            (ki.append(i) or kv.append(v)) if hit is None else merged.__setitem__(i, hit)
        return merged
    print(f"{'SIM':>5} {'dupe-recall':>12} {'false-merge':>13}")
    for sim in (0.65, 0.80, 0.88, 0.94):
        merged = dedup(sim)
        def res(i):
            while i in merged: i = merged[i]
            return i
        gc = sum(1 for m in gm.values() if len({res(i) for i in m}) == 1)
        fm = sum(1 for i in singles if i in merged)
        print(f"{sim:>5} {gc}/200={gc/200*100:>3.0f}% {fm}/{len(singles)}={fm/len(singles)*100:>4.1f}%")
    print("\nNo safe threshold: catches dupes -> heavy false-merge; low false-merge -> misses dupes.")
    print("=> semantic dedup is OPT-IN (PRECEDENT_EXTRACT_SEMANTIC_DEDUP=1); exact-text dedup is the safe default.")

if __name__ == "__main__":
    main()
