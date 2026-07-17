# Concepts

## Decision
The durable unit of knowledge. A decision is `situation → decision → why → authority`, with a scope
(paths + level) and provenance. Stored append-only; edits supersede.

## Authority ladder
`open-question → precedent → policy → guardrail`, increasing in force.
- **open-question** — nothing recorded; the agent is making a new decision (record it).
- **precedent** — a preference; follow unless you have a reason.
- **policy** — a standard; should follow.
- **guardrail** — a hard MUST/NEVER; overrides the agent's own judgment.

When several apply, **highest authority wins and a conflict beats a match** (a change can policy-match
one decision and guardrail-conflict another → the conflict dominates → deny).

## Levels: org / team / repo
A decision's scope has a **level**. The effective store for any repo is `org ∪ team ∪ repo`:
org/team decisions come from a central registry synced to every repo, so a team-transversal guardrail
(*never log PII*, *services emit structured JSON logs*) is enforced everywhere, not just where it was
written. **Dominance is by authority across levels** — a repo precedent cannot soften an org guardrail
(a team can't opt out). **Promotion widens scope** (repo → team → org). See [org-levels.md](org-levels.md).

## Risk (derived, not guessed)
Risk is computed deterministically from the tool, files, action, and environment across typed
dimensions (reversibility, production impact, security/data sensitivity, money movement, customer
visibility, cross-service impact, compliance, test coverage, rollback confidence) → a **tier**:
`low / medium / high / irreversible`. Domain sets a floor; the action's reversibility escalates it
(editing payment code = medium; deploying it = irreversible).

Plus a separate **consequentiality** axis (does the change add a new dependency/service/pattern, or is
it the first in an uncovered area?) — it decides whether a no-precedent change escalates (a real new
decision) or is gated by file-risk alone (a trivial change).

## The autonomy matrix
`authority × risk → verdict`, one of:
`act_silently` (auto), `act_and_flag` (auto, surfaced), `require_review`, `escalate`, `deny`.
A guardrail conflict is **deny**. An irreversible action **escalates** even under a matching guardrail.
The model supplies only the semantic half (which decision applies, match vs conflict, consequential);
deterministic code derives risk and applies the matrix. This makes verdicts model-independent, fast,
auditable, and reproducible.

## The autonomy frontier
The buyer-facing metric: the share of agent work that proceeds with **no human in the loop**, rising
week over week, backed by decisions the org itself recorded and can revoke — with the safety invariant
**zero harmful silent actions**.
