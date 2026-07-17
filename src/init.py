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

    # 3. agent surfaces, pointing at the vendored engine
    E = ".precedent/engine"
    w(os.path.join(target, ".mcp.json"), json.dumps({
        "mcpServers": {"precedent": {"command": "python3", "args": [f"{E}/mcp_server.py"]}}}, indent=2))
    w(os.path.join(target, ".github", "workflows", "precedent-gate.yml"), _WORKFLOW.replace("{E}", E))
    shutil.copy(os.path.join(PREC_ROOT, "AGENTS.md"), os.path.join(target, "AGENTS.md"))
    with open(os.path.join(target, "AGENTS.md")) as f:
        agents = f.read().replace("python3 src/", f"python3 {E}/")
    w(os.path.join(target, "AGENTS.md"), agents)
    skill_src = os.path.join(PREC_ROOT, ".claude", "skills", "precedent", "SKILL.md")
    if os.path.exists(skill_src):
        with open(skill_src) as f:
            w(os.path.join(target, ".claude", "skills", "precedent", "SKILL.md"),
              f.read().replace("python3 src/", f"python3 {E}/"))

    print(f"✓ Precedent initialized in {target}")
    print(f"  engine:   {E}/  (vendored)")
    print(f"  store:    .precedent/decisions.json  ({'existing, kept' if os.path.getsize(dec)>30 else 'empty'})")
    print("  surfaces: AGENTS.md · .mcp.json · Claude skill · .github/workflows/precedent-gate.yml")
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
