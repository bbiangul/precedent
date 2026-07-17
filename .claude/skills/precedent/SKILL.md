---
name: precedent
description: Consult and record team decisions when coding in this repo — retrieve applicable precedents before any non-trivial choice, run govern before merge/deploy, and record every new decision so the next agent inherits it. Use whenever choosing a library/pattern/data store, touching payments/checkout/auth/catalog, adding an endpoint, doing a migration, or making any architectural or reuse choice.
---

# Precedent — the team's decision memory and permission path

This repo routes coding-agent autonomy through **Precedent**: the org's recorded decisions, their
authority, and the *why*. Your job is to consult it before deciding, obey it, and grow it. An
unrecorded decision is how the next agent repeats a mistake you already avoided.

## 1. Before you decide — retrieve
Before any non-trivial choice (library, data store, error/retry pattern, touching
`payments/`/`checkout/`/`catalog/`/auth, adding an endpoint, a migration, **or reusing vs
rebuilding a capability**), consult first:

```
python3 src/precedent.py retrieve "<what you're deciding + files involved>"
```

- **guardrail** authority overrides your own judgment — follow it.
- **escalate**, or irreversible action (prod/money/deletes/migration) → stop, ask a human.
- **"no recorded decision applies"** → you're making a NEW decision → §3.

## 2. Before you merge/deploy — govern
For a concrete change/PR, get the autonomy verdict:

```
python3 src/govern_cli.py --paths <files> --title "<what + why>"
```

Verdicts: `act_silently`/`act_and_flag` = proceed; `require_review`/`escalate`/`deny` = **do not
proceed**, a human decides. In-loop, the MCP `govern` tool returns the same verdict.

## 3. After you decide — record (this is the part agents skip; don't)
Record the moment you: make a new decision, choose between alternatives, discover a constraint the
code doesn't state, get corrected by a reviewer, or **reuse (or deliberately don't reuse) an
existing capability**. One line — the service structures it:

```
python3 src/precedent.py record "situation: <...>; decided <X>; because <why>; scope <paths>"
```

**Always record when:** govern says the change is consequential with no precedent (you're setting a
new pattern); you pick a canonical source of truth ("consume the onboarding output, don't re-parse");
you ban or standardize an approach. Recorded decisions enter as **unconfirmed** and become
authoritative only when a human promotes them — so record liberally, the cost of a false record is low.

## Rule of thumb
**Retrieve before you choose. Govern before you merge. Record after you choose. Every time.**
Especially record the tacit ones (reuse/canonical-source/architecture) — those live only in your head
until you write them, and that is exactly the knowledge the next agent lacks.
