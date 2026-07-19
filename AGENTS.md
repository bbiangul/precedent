# Working in this repo — agent instructions

This repo is backed by a **Precedent service**: the org's recorded decisions and the
*why* behind them. It is not optional context — consult it and contribute to it.

## Before you decide (retrieve)
Before any non-trivial choice — a library, a data store, an error-handling pattern,
touching `payments/` `checkout/` `catalog/` or auth, adding an endpoint, a migration,
or anything you'd normally guess — ask first:

```
python3 src/precedent.py retrieve "<one line: what you're deciding + files involved>"
```

- Follow anything returned at **guardrail** authority — it overrides your own judgment.
- If it says **escalate**, or the action is irreversible (prod/money/deletes/migration), **stop and ask a human** instead of acting.
- If it returns "no recorded decision applies", you're making a new decision — see below.

## Before you merge/deploy (govern)
For a concrete change/PR, get the autonomy verdict — it decides whether you may proceed unattended:

```
python3 src/govern_cli.py --paths <files> --title "<what + why>"
```

`act_silently`/`act_and_flag` → proceed. `require_review`/`escalate`/`deny` → **stop, a human decides.**
In-loop, call the MCP `govern` tool instead. When govern blocks or says "no precedent", it tells you to record — do it.

## After you decide (record) — do this every time
The moment you make a decision, or discover a constraint the code doesn't state,
record it. **One line of free text — the service structures it for you:**

```
python3 src/precedent.py record "<situation>; decided <X>; because <why>; scope <paths>"
```

That's the whole burden — no schema, no form. Record liberally: an unrecorded decision
is exactly how the next agent repeats the mistake you just avoided. Your captured
decisions enter as **unconfirmed** and become authoritative only when a human promotes them.

## When a decision is wrong or outdated (propose deprecation)
If a recorded decision now contradicts reality or a newer decision replaces it, don't silently work
around it — **propose retiring it**:

```
python3 src/precedent.py deprecate <id> --reason "<why it's outdated>" [--superseded-by <newid>] --propose
```

You **propose**; it stays active and enforced until a human confirms (`confirm-deprecation <id>`) — you
can't retract a decision on your own. In-loop, use the MCP `deprecate_precedent` tool. Deprecating keeps
the store honest so the next agent doesn't inherit a stale rule.

> Rule of thumb: **retrieve before you choose, record after you choose, propose-deprecate when one goes stale.**

## Store hygiene (maintenance — NOT the coding loop)
Do **not** run this inline while coding — it's a batch pass (CI/nightly, or when a human asks you to
"audit/clean up the decision store"). It surfaces **contradictions** (two rules that can't both hold) and
decisions whose PRs keep going wrong, as deprecation **proposals** a human confirms:

```
python3 src/hygiene.py            # report contradictions + stale decisions
python3 src/hygiene.py --propose  # file the proposals
```
