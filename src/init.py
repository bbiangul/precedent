#!/usr/bin/env python3
"""`precedent init <repo>` — wire Precedent into a target repository. Made to be run BY AN AI AGENT.

It vendors the engine into the target (self-contained, no external dependency after), seeds an empty
decision store + the risk policy + the autonomy matrix, and drops in the agent-facing surfaces:
AGENTS.md, the MCP server registration, the Claude Code skill, and the CI gate workflow — all with
paths pointing at the vendored engine. Idempotent: won't clobber an existing decision store.

Usage:
  python3 src/init.py /path/to/target-repo     # or "." for the current repo
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))          # .../precedent/src
PREC_ROOT = os.path.dirname(HERE)


def w(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def main(target):
    target = os.path.abspath(target)
    prec = os.path.join(target, ".precedent")
    engine = os.path.join(prec, "engine")
    if os.path.abspath(target) == os.path.abspath(PREC_ROOT):
        sys.exit("refusing to init Precedent into its own source tree; pass a target repo.")
    os.makedirs(prec, exist_ok=True)

    # 1. vendor the engine (self-contained)
    if os.path.exists(engine):
        shutil.rmtree(engine)
    shutil.copytree(os.path.join(PREC_ROOT, "src"), engine,
                    ignore=shutil.ignore_patterns("__pycache__", "init.py", "measure_speed.py"))

    # 2. seed config (don't clobber an existing decision store)
    dec = os.path.join(prec, "decisions.json")
    if not os.path.exists(dec):
        w(dec, json.dumps({"precedents": []}, indent=2))
    for f in ("risk-policy.json", "autonomy-matrix.json"):
        shutil.copy(os.path.join(PREC_ROOT, ".precedent", f), os.path.join(prec, f))

    # 2b. protect the user's secret: ensure the target .gitignore excludes the key + runtime state
    #     (a target without this would commit .precedent/.env — violating guardrail PREC-3).
    gi = os.path.join(target, ".gitignore")
    need = [".precedent/.env", ".precedent/captured.json", ".precedent/verdicts.jsonl",
            ".precedent/events.jsonl", ".precedent/outcomes.jsonl", ".precedent/session_touch.jsonl",
            ".precedent/engine/__pycache__/"]
    have = open(gi).read() if os.path.exists(gi) else ""
    missing = [p for p in need if p not in have]
    if missing:
        with open(gi, "a") as f:
            f.write(("\n" if have and not have.endswith("\n") else "") + "\n# Precedent (keep secrets/state out of git)\n" + "\n".join(missing) + "\n")

    # 3. agent surfaces, pointing at the vendored engine. NEVER clobber the user's existing files.
    E = ".precedent/engine"

    def w_safe(rel, content):
        path = os.path.join(target, rel)
        if os.path.exists(path):
            print(f"  · kept your existing {rel} (Precedent version at {rel}.precedent-suggested)")
            w(path + ".precedent-suggested", content)
        else:
            w(path, content)

    w_safe(".mcp.json", json.dumps({
        "mcpServers": {"precedent": {"command": "python3", "args": [f"{E}/mcp_server.py"]}}}, indent=2))
    w_safe(".github/workflows/precedent-gate.yml", _WORKFLOW.replace("{E}", E))
    with open(os.path.join(PREC_ROOT, "AGENTS.md")) as f:
        w_safe("AGENTS.md", f.read().replace("python3 src/", f"python3 {E}/"))
    # Claude Code reads CLAUDE.md; point it at the full guidance in AGENTS.md (no-clobber)
    w_safe("CLAUDE.md", "# Project instructions for Claude\n\n"
           "This repo uses **Precedent** — a decision layer for agents. Follow **[AGENTS.md](AGENTS.md)**:\n"
           "retrieve before you choose, govern before you merge, record after you choose, "
           "propose-deprecate when a decision goes stale. The `precedent` MCP tools and CLI "
           f"(`python3 {E}/precedent.py ...`) are available.\n")
    skill_src = os.path.join(PREC_ROOT, ".claude", "skills", "precedent", "SKILL.md")
    if os.path.exists(skill_src):
        with open(skill_src) as f:
            w_safe(".claude/skills/precedent/SKILL.md", f.read().replace("python3 src/", f"python3 {E}/"))

    print(f"✓ Precedent initialized in {target}")
    print(f"  engine:   {E}/  (vendored)")
    print(f"  store:    .precedent/decisions.json  ({'existing, kept' if os.path.getsize(dec)>30 else 'empty'})")
    print("  surfaces: AGENTS.md · CLAUDE.md · .mcp.json · Claude skill · .github/workflows/precedent-gate.yml")
    print("\nNext:")
    print("  1. export OPENROUTER_API_KEY=...  (and add it as a repo secret for CI)")
    print(f"  2. seed the store:  python3 {E}/extract/extract_decisions.py .   "
          f"and/or  python3 {E}/extract/mine_enforcements.py")
    print("  3. make the 'Precedent gate' a required status check in branch protection")
    print(f"  4. use it:  python3 {E}/precedent.py retrieve \"<what you're deciding>\"")


_WORKFLOW = """name: Precedent gate
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
jobs:
  govern:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: govern(diff)
        id: gov
        env:
          GITHUB_BASE_REF: ${{ github.base_ref }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          set +e
          python3 {E}/govern_cli.py --title "${{ github.event.pull_request.title }}" > verdict.md
          echo "allow=$?" >> "$GITHUB_OUTPUT"
          cat verdict.md
      - name: Post verdict
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            await github.rest.issues.createComment({ owner: context.repo.owner, repo: context.repo.repo,
              issue_number: context.issue.number, body: fs.readFileSync('verdict.md','utf8') });
      - name: Enforce
        if: steps.gov.outputs.allow != '0'
        run: |
          echo "::error::Precedent gate blocked this merge - see the verdict comment."
          exit 1
"""

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 src/init.py <target-repo-dir>")
    main(sys.argv[1])
