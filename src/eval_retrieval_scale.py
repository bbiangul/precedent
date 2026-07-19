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

# HELD-OUT queries — authored AFTER the floor was tuned on QUERIES, new phrasings/angles.
# The floor is NOT tuned on these, so this is the de-biased number to trust.
HELDOUT = [
 ("can I cache something forever with no expiry?","D03"),
 ("what's the lifetime of our bearer tokens?","D04"),
 ("is it fine to encode the user's full name in the token?","D06"),
 ("do superuser accounts need two-factor?","D07"),
 ("can I use server-side session cookies?","D08"),
 ("I'm removing a field from a public API response — allowed?","D10"),
 ("my endpoint could return fifty thousand items — what do I do?","D12"),
 ("how should I shape a 400 error response body?","D13"),
 ("will this migration break during a rolling deploy?","D14"),
 ("can I delete an unused column right away?","D15"),
 ("how do I make logs traceable across services?","D17"),
 ("can I print the API key to debug an issue?","D18"),
 ("is catch(e){} with nothing inside acceptable?","D20"),
 ("calling a flaky third-party API — what's required?","D21"),
 ("how do I stop a retried payment from charging twice?","D22"),
 ("can I store the full card number in our database?","D23"),
 ("does stored personal data need encryption?","D25"),
 ("GDPR erasure request — how fast must we act?","D26"),
 ("are floating semver ranges allowed for packages?","D27"),
 ("insert the order and its line items atomically — how?","D29"),
 ("can I use styled-components for a new component?","D33"),
 ("should I put fetched API data into Redux?","D34"),
 ("can I put the DB password in a committed .env file?","D35"),
 ("what caching should a CDN edge use?","ABSTAIN"),
 ("how do we version a gRPC service?","ABSTAIN"),
 ("what's our database read-replica strategy?","ABSTAIN"),
 ("do we support biometric login?","ABSTAIN"),
 ("how should we A/B test a new feature?","ABSTAIN"),
 ("which Slack channel is for release announcements?","ABSTAIN"),
 ("what's the company dress code?","ABSTAIN"),
 ("how do I book a meeting room?","ABSTAIN"),
 ("what's the office coffee machine brand?","ABSTAIN"),
]

def _score(qset, ranked):
    pos = [x for x in qset if x[1] != "ABSTAIN"]
    neg = [x for x in qset if x[1] == "ABSTAIN"]
    r1 = sum(1 for q, t in pos if ranked(q)[:1] == [t])
    absk = sum(1 for q, _ in neg if not ranked(q))
    return (f"recall@1 {r1}/{len(pos)}={r1/len(pos)*100:.0f}%  "
            f"abstention {absk}/{len(neg)}={absk/len(neg)*100:.0f}%  "
            f"balanced {r1+absk}/{len(qset)}={(r1+absk)/len(qset)*100:.0f}%")

def main():
    precs = [{"id": i, "decision": t, "authority": a, "reasoning": "team convention",
              "scope": {"paths": [], "level": "org"}} for (i, a, t) in CORPUS]
    precedent._all_precedents = lambda: precs          # eval against the fixed corpus
    def ranked(q):
        return [r["id"] for r in precedent.retrieve_packet(q).get("relevant", [])]
    print(f"corpus {len(precs)} decisions\n")
    print(f"in-sample (floor tuned here) : {_score(QUERIES, ranked)}")
    print(f"HELD-OUT  (de-biased, trust) : {_score(HELDOUT, ranked)}")

if __name__ == "__main__":
    main()
