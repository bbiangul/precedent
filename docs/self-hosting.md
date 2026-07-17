# Self-hosting

Precedent runs entirely in your environment — decisions never leave your infrastructure.

## Install
```bash
git clone https://github.com/bbiangul/precedent && cd precedent
```
Python 3.9+. The hot path (scope + local keyword/embedding retrieval + the deterministic gate) uses
only the standard library. The semantic steps (govern's match/conflict judgment, retrieval embeddings)
call an OpenAI-compatible endpoint — set:
```bash
export OPENROUTER_API_KEY=...          # or any OpenAI-compatible key
export ARM_MODEL=deepseek/deepseek-v4-flash   # any capable model; a small one works
```
Keep the key in `.precedent/.env` (gitignored) or your secret manager — never commit it.

## Seed the store
An empty store is the adoption killer. Seed from what your team already decided:
```bash
python3 src/extract/extract_decisions.py <path-to-a-repo>   # ADRs / RFCs / convention docs
python3 src/extract/mine_enforcements.py                    # PR review comments (needs `gh`)
```
Both produce decisions with `authority`, `scope`, and provenance. Mined entries land as `status:mined`
until a human promotes them (admission control).

## The CI gate
`.github/workflows/precedent-gate.yml` runs `govern(diff)` on every PR and posts the verdict as a
comment; a non-allow verdict fails the required check and blocks the merge. Add `OPENROUTER_API_KEY` as
a repo secret. Make the check **required** in branch protection to enforce it.

## Org/team decisions
Point `PRECEDENT_SHARED` at a shared decisions file (synced from a central registry) to enforce
team/org-wide decisions across every repo. See [org-levels.md](org-levels.md).
