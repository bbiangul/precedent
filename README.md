<div align="center">

# 🔐 Precedent

**The decision layer & permission layer for AI coding agents.**

[![npm](https://img.shields.io/npm/v/precedent-cli?color=22c99a&label=precedent-cli)](https://www.npmjs.com/package/precedent-cli)
[![license](https://img.shields.io/npm/l/precedent-cli?color=22c99a)](LICENSE)
[![site](https://img.shields.io/badge/precedent.sh-live-22c99a)](https://precedent.sh)

Your agents keep re-deciding things your team already settled — which library, which pattern,
whether to touch payments. Precedent records those decisions once, serves them back to the agent
*before* it acts, and enforces them at the merge gate. Watch the share of agent work that runs
safely unattended go up, week over week.

[Quickstart](#-quickstart-60-seconds) · [How agents use it](docs/for-ai-agents.md) · [Concepts](docs/concepts.md) · [Self-hosting](docs/self-hosting.md) · [llms.txt](llms.txt)

</div>

---

## Why

An AI coding agent has no memory of your team's decisions. It reinvents a feature-flag system you
standardized months ago, re-parses data a pipeline already prepared, reaches for Redux where your
team banned it. The durable unit of knowledge isn't a fact — it's a **decision**: *the situation, what
was decided, why, and its authority.*

Precedent captures decisions and puts them in the loop, two ways:

- **In the session** (Claude Code / Cursor / Codex / any MCP or hook-capable agent): before a
  non-trivial action, the agent asks `govern()` — *is this already decided? may I act, should I flag,
  or must a human decide?* — and records new decisions as it makes them.
- **At the boundary** (the git/PR/CI gate): a deterministic check enforces the same decisions where it
  can actually block — auto-merge what has precedent and is low-risk, escalate what's new and
  consequential, deny a guardrail violation.

The two are symbiotic: the gate makes consulting *worth it* (the same rules block at merge), and the
in-session layer makes the gate *cheap* (it prevents the bad change instead of just blocking it — and
grows the decision store).

## ✨ Quickstart (60 seconds)

### Install into your repo — one command

```bash
npx precedent-cli init          # vendors the engine + wires every agent harness
```

`init` drops Precedent into every agent you run **without overwriting your existing rules** —
it appends a marked block to `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / `.github/copilot-instructions.md`,
writes `.cursor/rules` + `.windsurf/rules` + the Claude Code skill, and merges the `precedent`
MCP server into `.mcp.json` / `.cursor/mcp.json` (keeping your other servers). Then:

```bash
npx precedent-cli retrieve "add a caching layer to the dashboard"
npx precedent-cli govern --paths web/Chart.tsx --title "Add Redux for server-state"
npx precedent-cli record "situation: …; decided …; because …; scope web/**"
npx precedent-cli hygiene --propose      # batch: contradictions + stale decisions
```

Requires Python 3.9+ on PATH (the engine is stdlib-only for the hot path — no heavy deps).

### Or run from source

```bash
git clone https://github.com/bbiangul/precedent && cd precedent

# 1. See the autonomy matrix resolve on 12 example changes
python3 src/govern.py

# 2. Ask whether a change is allowed (uses the seed decisions in .precedent/)
python3 src/govern_cli.py --paths web/dashboards/Chart.tsx \
        --title "Add Redux for dashboard server-state caching"
#  ⛔ BLOCK — denied: violates guardrail E2 (Redux is banned for server-state caching)

# 3. Retrieve the decisions that apply to what you're about to do
python3 src/precedent.py retrieve "add a caching layer to the dashboard"

# 4. Record a new decision (the store grows itself)
python3 src/precedent.py record "situation: adding feature flags; decided flags go through the \
        superadmin panel; because central control; scope web/**"
```

An LLM key is only needed for the *semantic* steps (govern's match/conflict judgment, retrieval
embeddings). Set `OPENROUTER_API_KEY` (any OpenAI-compatible endpoint via `ARM_MODEL`). The
**enforcement gate itself makes zero model calls** — it's deterministic.

## 🤖 Built for agents first

Precedent is infrastructure for AI agents, and friendly for the humans who supervise them. An agent
sets it up and uses it without you holding its hand:

| Surface | What the agent does |
|---|---|
| **MCP server** (`src/mcp_server.py`) | `retrieve_precedent`, `govern`, `record_precedent` as MCP tools — works in Claude Code, Cursor, Codex |
| **CLI** | `govern_cli.py`, `precedent.py retrieve/record` — for any harness that runs shell |
| **Hooks** (`src/hooks/`) | a `PreToolUse` tripwire that injects applicable decisions into the agent's context (≈30ms, 0 model calls) and a `Stop` nudge to record new decisions |
| **Skill + AGENTS.md** | drop-in guidance so the agent knows to retrieve-before / govern-before-merge / record-after |
| **llms.txt** | so ChatGPT/Claude/Cursor/Codex can discover and understand Precedent when they search |

See [docs/for-ai-agents.md](docs/for-ai-agents.md) — including a copy-paste block you can hand any
agent to have it wire Precedent into your repo.

## Core concepts

- **Decision** — `situation → decision → why → authority`, path- and level-scoped.
- **Authority ladder** — `open-question → precedent → policy → guardrail`. A guardrail overrides the
  agent's judgment; a conflict beats a match.
- **Levels** — `org / team / repo`. A team-transversal guardrail (e.g. *never log PII*) is enforced in
  every repo, not just where it was written. Promotion widens scope (repo → team → org).
- **Autonomy matrix** — `authority × risk → verdict` (`act_silently / act_and_flag / require_review /
  escalate / deny`). Risk is derived deterministically; the model only judges which decision applies
  and whether the change matches or conflicts.
- **Autonomy frontier** — the metric: the fraction of agent work that runs with no human in the loop,
  with zero harmful silent actions.

Full write-up in [docs/concepts.md](docs/concepts.md).

## Honest status

Precedent is early and built in the open, with its homework shown. What's solid, and what isn't:

- ✅ **Enforcement** (the deterministic gate) and the **govern architecture** (model-independent:
  matches frontier models on a small 31B model) are validated.
- ✅ **Cross-harness**: the loop closes end-to-end in real Claude Code *and* Codex sessions.
- ⚠️ **Retrieval at scale** is ~60–66% on one real repo (Backstage) — a ground-truth-quality problem,
  not a model one. Numbers are directional; a publishable claim needs multi-repo, human-labeled data.
- We run an **adversarial review** on our own results and retract what doesn't survive. See the
  `benchmark/` write-ups (in the research branch) for the receipts.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). This repo governs *itself* with
Precedent: the CI gate runs `govern(diff)` on every PR, and design decisions are recorded in
`.precedent/`. Licensed under [Apache 2.0](LICENSE).
