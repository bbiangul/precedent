# Org / team / repo levels

Some decisions are local to a repo; others are transversal — valid for the whole team or org
regardless of which repo an agent is in. Precedent models this with a `level` on each decision's scope.

## The model
```json
{ "id": "ORG-001", "authority": "guardrail",
  "scope": { "level": "org", "paths": [] },
  "decision": "PII (card numbers, SSNs, secrets) must never be written to logs." }
```
- `level: repo` — this repo only (the default).
- `level: team` — every repo owned by the team.
- `level: org` — every repo in the org.
- `paths: []` means "everywhere within the level"; a glob narrows it.

## Resolution
The effective store for a repo is `org ∪ team ∪ repo`. org/team decisions come from a central registry
synced to each repo (point `PRECEDENT_SHARED` at it; `src/govern.py:load_decisions`). A team-transversal
guardrail is therefore enforced in **all** the team's repos, not just where it was authored.

## Dominance & promotion
Dominance is by **authority across levels**: a repo-level precedent cannot soften an org-level guardrail
— a team can't opt out of an org rule. **Promotion widens scope** (repo → team → org): a decision that
proves general is promoted, and starts applying more broadly.
