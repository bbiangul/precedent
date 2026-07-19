#!/usr/bin/env python3
"""Scaled, ADVERSARIAL retrieval benchmark — a fixed synthetic corpus (with same-topic
distractors) and hand-labeled queries (paraphrased positives, near-misses, and pure
negatives). Measures recall@1/@3, MRR, and abstention/false-positive rate against
retrieve_packet as it actually ships. Reusable so retrieval changes are measured, not guessed.

  OPENROUTER_API_KEY=... python3 src/eval_retrieval_scale.py

Caveat: synthetic (corpus + queries authored together), so it's a controlled benchmark, not
production traffic — but the adversarial construction (distractors/near-misses/paraphrase) makes
it far more honest than trivial probes, and the headline number tracks the PRD's real ~60-66%.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import precedent

CORPUS = [
 ("D01","guardrail","All server-side caching must use Redis, not a local process cache."),
 ("D02","guardrail","In-memory per-process caches are banned for state shared across instances."),
 ("D03","policy","Every cache entry must have an explicit TTL; no unbounded cache entries."),
 ("D04","guardrail","Access tokens are JWTs that expire after 15 minutes."),
 ("D05","policy","Refresh tokens must be rotated on every use."),
 ("D06","guardrail","Never put personally identifiable information in a JWT payload."),
 ("D07","guardrail","Admin accounts must use multi-factor authentication to sign in."),
 ("D08","guardrail","Session state must never be stored on the server."),
 ("D09","guardrail","Public APIs are versioned in the URL path, e.g. /v1/ /v2/."),
 ("D10","policy","A breaking change to a public API requires a brand-new API version."),
 ("D11","policy","Every deprecated API version stays supported for at least 12 months."),
 ("D12","policy","List endpoints must be paginated; never return an unbounded collection."),
 ("D13","policy","API errors are returned as RFC7807 application/problem+json responses."),
 ("D14","guardrail","Database migrations must be backward-compatible for one deploy cycle."),
 ("D15","guardrail","No destructive column drops in the same release that stops writing them."),
 ("D16","policy","Migrations run in CI and must pass before a deploy proceeds."),
 ("D17","policy","All logs are structured JSON and include a request_id."),
 ("D18","guardrail","Never log secrets, tokens, or personally identifiable information."),
 ("D19","policy","Use the shared logger module, never console.log."),
 ("D20","guardrail","Never swallow exceptions with an empty catch; log and rethrow or return a typed error."),
 ("D21","policy","Every outbound call to an external service must have a timeout and bounded retries."),
 ("D22","guardrail","Charging a payment provider requires an idempotency key."),
 ("D23","guardrail","Never store raw card numbers; use the payment provider's token."),
 ("D24","policy","Payment ledgers are reconciled against the provider daily."),
 ("D25","guardrail","Personally identifiable information must be encrypted at rest."),
 ("D26","policy","A user data-deletion request must be honored within 30 days."),
 ("D27","policy","Dependency versions must be pinned; no floating version ranges."),
 ("D28","policy","Adding a new third-party dependency requires reviewer approval."),
 ("D29","guardrail","Multi-step database writes must run inside a single transaction."),
 ("D30","policy","Concurrent updates to a record use optimistic locking with a version column."),
 ("D31","policy","Every new API endpoint ships with integration tests."),
 ("D32","policy","Service code must maintain at least 80% test coverage."),
 ("D33","guardrail","All styling uses Tailwind CSS; styled-components is banned."),
 ("D34","guardrail","Server state in the frontend uses React Query; Redux is banned for caching."),
 ("D35","guardrail","Secrets come from the vault, never committed in env files."),
 ("D36","policy","Prefer feature flags over long-lived release branches."),
]
QUERIES = [
 ("where should I keep a value that several app servers all read?","D01"),
 ("is it ok to cache things in a module-level dict across requests?","D02"),
 ("do cached entries need to expire?","D03"),
 ("how many minutes until a login access token stops working?","D04"),
 ("how does a client get a fresh token when its one expires?","D05"),
 ("can I put the customer's email address inside the token claims?","D06"),
 ("do administrators need something extra beyond a password to log in?","D07"),
 ("are we allowed to keep the user's session on the backend?","D08"),
 ("where in the request does the API version live?","D09"),
 ("I need to change the response shape of a public endpoint incompatibly — what do I do?","D10"),
 ("how long must we keep an old endpoint alive after announcing it's going away?","D11"),
 ("an endpoint returns thousands of rows — what's the rule?","D12"),
 ("what content type and shape should API error bodies use?","D13"),
 ("is it safe to remove a column in the release that stops using it?","D15"),
 ("what's the rule so a schema change doesn't break a rolling deploy?","D14"),
 ("must schema changes be checked before shipping?","D16"),
 ("what should every log line include for tracing?","D17"),
 ("is it fine to log the user's auth token for debugging?","D18"),
 ("someone used console.log — what should they use instead?","D19"),
 ("I see an empty catch block — is that allowed?","D20"),
 ("what must I add when calling a third-party HTTP service?","D21"),
 ("do I need anything special charging a card to avoid double charges?","D22"),
 ("can I save the raw credit card number in our DB?","D23"),
 ("how often do we check payments match the provider?","D24"),
 ("does user PII need protection when stored?","D25"),
 ("a user asked us to delete their data — what's the deadline?","D26"),
 ("should package versions be locked down?","D27"),
 ("can I just add a new npm library on my own?","D28"),
 ("two writes must both succeed or neither — how?","D29"),
 ("how do we avoid two updates clobbering each other on the same row?","D30"),
 ("does my new endpoint require tests?","D31"),
 ("what CSS approach do we use for components?","D33"),
 ("how do I manage data fetched from the server in React?","D34"),
 ("where do production secrets come from?","D35"),
 ("is a three-week release branch ok?","D36"),
 # near-misses (adjacent topic, NOT decided) -> ABSTAIN
 ("what caching should the browser use for assets?","ABSTAIN"),
 ("how should we version our GraphQL schema?","ABSTAIN"),
 ("should we shard the primary database?","ABSTAIN"),
 ("which social OAuth providers do we support?","ABSTAIN"),
 ("what algorithm should hash user passwords?","ABSTAIN"),
 ("what's our API rate-limiting strategy?","ABSTAIN"),
 ("which message queue should background jobs use?","ABSTAIN"),
 ("how do we do canary deployments?","ABSTAIN"),
 # pure negatives -> ABSTAIN
 ("what color should the primary button be?","ABSTAIN"),
 ("which tool do we use for daily standups?","ABSTAIN"),
 ("what laptop do new engineers get?","ABSTAIN"),
 ("how many vacation days do we have?","ABSTAIN"),
 ("what font should the marketing blog use?","ABSTAIN"),
 ("what's the office wifi password?","ABSTAIN"),
]

def main():
    precs = [{"id": i, "decision": t, "authority": a, "reasoning": "team convention",
              "scope": {"paths": [], "level": "org"}} for (i, a, t) in CORPUS]
    precedent._all_precedents = lambda: precs          # eval against the fixed corpus
    def ranked(q):
        return [r["id"] for r in precedent.retrieve_packet(q).get("relevant", [])]
    pos = [x for x in QUERIES if x[1] != "ABSTAIN"]
    neg = [x for x in QUERIES if x[1] == "ABSTAIN"]
    r1 = r3 = mrr = 0
    for q, t in pos:
        ids = ranked(q)
        if ids[:1] == [t]: r1 += 1
        if t in ids[:3]: r3 += 1
        if t in ids: mrr += 1 / (ids.index(t) + 1)
    absk = sum(1 for q, _ in neg if not ranked(q))
    print(f"corpus {len(precs)} decisions | {len(pos)} positive + {len(neg)} abstain queries\n")
    print(f"recall@1   : {r1}/{len(pos)} = {r1/len(pos)*100:.0f}%")
    print(f"recall@3   : {r3}/{len(pos)} = {r3/len(pos)*100:.0f}%")
    print(f"MRR        : {mrr/len(pos):.2f}")
    print(f"abstention : {absk}/{len(neg)} = {absk/len(neg)*100:.0f}%  (false-positive {(len(neg)-absk)/len(neg)*100:.0f}%)")
    print(f"balanced   : {r1+absk}/{len(QUERIES)} = {(r1+absk)/len(QUERIES)*100:.0f}%  (recall@1 + abstention)")

if __name__ == "__main__":
    main()
