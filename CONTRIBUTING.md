# Contributing to Precedent

Thanks for helping build the decision layer for AI agents. Issues and PRs are welcome.

## This repo governs itself
Precedent runs on its own PRs: the CI gate (`.github/workflows/precedent-gate.yml`) calls
`govern(diff)` on every change, and design decisions live in `.precedent/`. If the gate flags your PR,
it's citing a recorded decision — comply, or open a discussion to change the decision.

## Ground rules
- **Retrieve before you choose, record after you choose.** If you make a design decision, record it:
  `python3 src/precedent.py record "situation; decided X; because Y; scope <paths>"`.
- **Keep the hot path dependency-free.** Scope, local retrieval, and the deterministic gate use only
  the standard library. Heavy/optional deps (embeddings, local models) must degrade gracefully.
- **No secrets in git.** The API key lives in `.precedent/.env` (gitignored) or a secret manager.
- **Show your homework.** Benchmark or measurement claims need a reproducible script and honest
  caveats. We run adversarial review on our own numbers and retract what doesn't survive — please do too.

## Dev setup
```bash
git clone https://github.com/bbiangul/precedent && cd precedent
export OPENROUTER_API_KEY=...  ARM_MODEL=deepseek/deepseek-v4-flash
python3 src/govern.py          # should print 12/12
```

## PRs
Small, focused, with a one-line "why". By contributing you agree your work is licensed under Apache 2.0.
