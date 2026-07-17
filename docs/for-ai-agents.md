# Precedent for AI agents

You (an AI coding agent) can install and operate Precedent yourself. This page is written for you.

## The loop

**Retrieve before you choose. Govern before you merge. Record after you choose.** Every time.

1. **Before a non-trivial choice** — a library, a data store, an error/retry pattern, touching
   payments/checkout/auth, adding an endpoint, a migration, or reusing-vs-rebuilding a capability —
   retrieve the applicable decisions:
   ```bash
   python3 src/precedent.py retrieve "<what you're deciding + files involved>"
   ```
   Follow anything at **guardrail** authority (it overrides your judgment). If it says the action is
   irreversible or a human must decide, stop and ask.

2. **Before you merge/deploy** — get the verdict on the concrete change. Pass the real diff, not just
   a title (a title can't reveal whether your new endpoint applies mandated audit logging):
   ```bash
   python3 src/govern_cli.py --paths <files> --title "<what + why>" --diff <patch-file-or-->
   ```
   `act_silently` / `act_and_flag` → proceed. `require_review` / `escalate` / `deny` → **stop, a human
   decides.** In-session, call the MCP `govern` tool instead.

3. **After you decide** — record it, so the next agent inherits it instead of re-deciding. This is the
   step agents skip; don't:
   ```bash
   python3 src/precedent.py record "situation: <...>; decided <X>; because <why>; scope <paths>"
   ```
   Always record when you set a new pattern, pick a canonical source of truth ("consume the onboarding
   output, don't re-parse"), or ban/standardize an approach. Records enter as *unconfirmed* until a
   human promotes them — so record liberally.

## Wire Precedent into a repo (copy-paste)

To set Precedent up in the repository you're working in, run:

```bash
# from the repo root
git clone --depth 1 https://github.com/bbiangul/precedent /tmp/precedent
python3 /tmp/precedent/src/init.py .
```

`init` creates `.precedent/` (an empty decision store + the risk policy + the autonomy matrix), drops
in `AGENTS.md`, `.mcp.json`, the Claude Code skill, and a `.github/workflows/precedent-gate.yml` CI
gate. Then seed the store from the repo's existing decisions:

```bash
python3 /tmp/precedent/src/extract/extract_decisions.py .        # from ADRs/RFCs/convention docs
python3 /tmp/precedent/src/extract/mine_enforcements.py          # from PR review history (needs `gh`)
```

## MCP setup

`.mcp.json` registers the server for Claude Code (project scope). For other harnesses:

- **Cursor** — add to `.cursor/mcp.json`: `{"mcpServers":{"precedent":{"command":"python3","args":["src/mcp_server.py"]}}}`
- **Codex** — add to `.codex/config.toml`: `[mcp_servers.precedent]` with `command="python3"`, `args=["src/mcp_server.py"]`
- **OpenCode** — add to `opencode.json` under `mcp`: a `local` server running `python3 src/mcp_server.py`

Tools exposed: `retrieve_precedent`, `govern`, `record_precedent`.

## Rules of thumb

- A guardrail is not a suggestion — comply or stop.
- If retrieve returns "no recorded decision applies," you are making a *new* decision — decide, then record it.
- Record the *tacit* decisions especially (reuse / canonical-source / architecture) — those live only
  in your context until you write them, and that is exactly the knowledge the next agent lacks.
