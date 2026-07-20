#!/usr/bin/env python3
"""`precedent init <repo>` — wire Precedent into a target repository. Made to be run BY AN AI AGENT.

It vendors the engine into the target (self-contained, no external dependency after), seeds an empty
decision store + the risk policy + the autonomy matrix, and drops in the agent-facing surfaces:
AGENTS.md, the MCP server registration, the Claude Code skill, and the CI gate workflow — all with
paths pointing at the vendored engine. Idempotent: won't clobber an existing decision store.

Usage:
  python3 src/init.py /path/to/target-repo     # or "." for the current repo
"""
import json, os, re, shutil, subprocess, sys

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

    # 3. agent surfaces for every major harness. NEVER clobber the user's existing rules:
    #    shared instruction files get a marker-delimited block appended (or updated in place);
    #    MCP config is merged (other servers kept); Precedent-owned files are written outright.
    E = ".precedent/engine"
    A, B = "<!-- precedent:start -->", "<!-- precedent:end -->"

    def _mkdirs(path):
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)

    def upsert(rel, body):
        """Insert/refresh a Precedent block between markers, preserving everything else."""
        path = os.path.join(target, rel)
        _mkdirs(path)
        section = f"{A}\n{body.rstrip()}\n{B}"
        if os.path.exists(path):
            cur = open(path).read()
            if A in cur and B in cur:
                new = re.sub(re.escape(A) + r"[\s\S]*?" + re.escape(B), lambda _m: section, cur)
                act = "refreshed Precedent block in"
            else:
                new = cur.rstrip() + "\n\n" + section + "\n"
                act = "appended Precedent block to your existing"
        else:
            new = section + "\n"
            act = "created"
        w(path, new)
        print(f"  · {act} {rel}")

    def merge_mcp(rel, args):
        """Add the precedent MCP server without dropping the user's other servers."""
        path = os.path.join(target, rel)
        _mkdirs(path)
        data = {}
        if os.path.exists(path):
            try:
                data = json.load(open(path))
            except Exception:
                print(f"  · {rel} exists but isn't valid JSON — skipped (add precedent manually)")
                return
        kept = [k for k in data.get("mcpServers", {}) if k != "precedent"]
        data.setdefault("mcpServers", {})["precedent"] = {"command": "python3", "args": args}
        w(path, json.dumps(data, indent=2) + "\n")
        print(f"  · registered precedent MCP in {rel}" + (f" (kept: {', '.join(kept)})" if kept else ""))

    def owned(rel, content):
        """Precedent-namespaced file — safe to write/refresh outright."""
        path = os.path.join(target, rel)
        _mkdirs(path)
        w(path, content)
        print(f"  · wrote {rel}")

    # concise cross-harness pointer (full guidance lives in AGENTS.md / the skill)
    pointer = ("## Precedent — the decision layer (auto-installed)\n\n"
        "This repo uses **Precedent**. Before you change code, **retrieve** the decisions that bind; "
        "at the merge gate, **govern**; after you decide, **record**; when a decision is stale or wrong, "
        "**propose deprecation** (agents propose — a human retires). Full guidance: `AGENTS.md`.\n\n"
        f"- retrieve:  `python3 {E}/precedent.py retrieve \"<what you're deciding>\"`\n"
        f"- govern:    `python3 {E}/govern_cli.py --paths <files> --title \"<change>\"`\n"
        f"- record:    `python3 {E}/precedent.py record \"<situation; decided X; because Y; scope>\"`\n"
        f"- deprecate: `python3 {E}/precedent.py deprecate <id> --reason \"<why>\"`\n\n"
        "The MCP server `precedent` exposes the same tools.\n")

    # CI gate — Precedent-owned, but never clobber a user's edited copy
    wf = os.path.join(target, ".github/workflows/precedent-gate.yml")
    if not os.path.exists(wf):
        owned(".github/workflows/precedent-gate.yml", _WORKFLOW.replace("{E}", E))

    # shared instruction files (append-safe) — one per harness family that reads them
    with open(os.path.join(PREC_ROOT, "AGENTS.md")) as f:
        agents_full = f.read().replace("python3 src/", f"python3 {E}/")
    upsert("AGENTS.md", agents_full)          # Codex · OpenCode · Cursor · Jules · Aider · Zed
    upsert("CLAUDE.md", pointer)              # Claude Code
    upsert("GEMINI.md", pointer)              # Gemini CLI
    upsert(".github/copilot-instructions.md", pointer)   # GitHub Copilot

    # Precedent-owned rule files (harness-specific namespaces)
    owned(".cursor/rules/precedent.mdc",
          "---\ndescription: Precedent — team decisions that bind this repo\nalwaysApply: true\n---\n\n" + pointer)
    owned(".windsurf/rules/precedent.md", pointer)       # Windsurf / Codeium
    skill_src = os.path.join(PREC_ROOT, ".claude", "skills", "precedent", "SKILL.md")
    if os.path.exists(skill_src):
        with open(skill_src) as f:
            owned(".claude/skills/precedent/SKILL.md", f.read().replace("python3 src/", f"python3 {E}/"))

    # MCP registration (merged — other servers preserved)
    merge_mcp(".mcp.json", [f"{E}/mcp_server.py"])       # Claude Code · Codex · generic
    merge_mcp(".cursor/mcp.json", [f"{E}/mcp_server.py"])  # Cursor

    print(f"✓ Precedent initialized in {target}")
    print(f"  engine:   {E}/  (vendored)")
    print(f"  store:    .precedent/decisions.json  ({'existing, kept' if os.path.getsize(dec)>30 else 'empty'})")
    print("  harnesses: AGENTS.md (Codex/OpenCode/Cursor/Aider/Zed) · CLAUDE.md + skill (Claude Code) ·")
    print("             GEMINI.md · copilot-instructions.md · .cursor/rules · .windsurf/rules")
    print("  mcp:      .mcp.json · .cursor/mcp.json    ·    ci: .github/workflows/precedent-gate.yml")
    print("\nNext:")
    print("  1. export OPENROUTER_API_KEY=...   (a model key for the semantic steps)")
    print(f"  2. seed the store:  python3 {E}/extract/extract_decisions.py .   "
          f"and/or  python3 {E}/extract/mine_enforcements.py")
    print("  3. wire the CI gate on GitHub (agent-runnable):  npx precedent-cli init --github")
    print("     └ enforces the 'govern' check on the default branch; leaves you ONE step: `gh secret set OPENROUTER_API_KEY`")
    print(f"  4. use it:  npx precedent-cli retrieve \"<what you're deciding>\"")


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
          PR_TITLE: ${{ github.event.pull_request.title }}
        run: |
          set +e
          python3 {E}/govern_cli.py --json --title "$PR_TITLE" > verdict.json
          echo "allow=$?" >> "$GITHUB_OUTPUT"
          cat verdict.json
      - name: Post verdict (sticky — only when it blocks)
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const M = '<!-- precedent-gate -->';
            let v = {}; try { v = JSON.parse(fs.readFileSync('verdict.json', 'utf8')); } catch (e) {}
            const { owner, repo } = context.repo, issue_number = context.issue.number;
            const { data: cs } = await github.rest.issues.listComments({ owner, repo, issue_number });
            const prev = cs.find(c => c.body && c.body.includes(M));
            if (v.allow) {                              // clean PR: no noise; flip a prior block to resolved
              if (prev) await github.rest.issues.updateComment({ owner, repo, comment_id: prev.id,
                body: M + '\\n✅ **Precedent:** resolved — this change is within policy.' });
              return;
            }
            const head = v.verdict === 'deny' ? '⛔ **Precedent blocked this merge**'
              : '🟡 **Precedent — human review required**';
            const gov = (v.precedent_ids || []).join(', ') || '—';
            const det = ['<details><summary>verdict details</summary>', '', '```',
              'verdict: ' + v.verdict + '  authority: ' + v.authority_state + '  risk: ' + v.risk_tier,
              'governing: ' + gov + '  consequential: ' + v.consequential, '```', '</details>'].join('\\n');
            const body = [M, head, '', '**Why:** ' + (v.why || ''), '`' + ((v.paths || []).join(', ')) + '`', '',
              'How to proceed: address the decision above, or record an exception with authority — `npx precedent-cli record ...`.',
              '', det].join('\\n');
            if (prev) await github.rest.issues.updateComment({ owner, repo, comment_id: prev.id, body });
            else await github.rest.issues.createComment({ owner, repo, issue_number, body });
      - name: Enforce
        if: steps.gov.outputs.allow != '0'
        run: |
          echo "::error::Precedent gate blocked this merge - see the verdict comment."
          exit 1
"""

def wire_github(target):
    """Wire the CI gate on GitHub, doing everything an agent CAN do autonomously — leaving the human
    exactly ONE step: sharing the secret. Every gh call is best-effort; on failure we print the manual
    command so setup still completes. Requires `gh` authenticated."""
    def gh(*args, **kw):
        return subprocess.run(["gh", *args], cwd=target, capture_output=True, text=True, **kw)
    print("\n── GitHub wiring (precedent init --github) ──")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        print("  gh not authenticated — run `gh auth login`, then re-run with --github. Skipping.")
        return
    repo = gh("repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    if repo.returncode != 0:
        print("  no GitHub repo detected here (add a remote / `gh repo create`). Skipping GitHub wiring.")
        return
    info = json.loads(repo.stdout)
    slug = info["nameWithOwner"]; branch = info.get("defaultBranchRef", {}).get("name", "main")
    owner = slug.split("/")[0]
    print(f"  repo: {slug}  (default branch: {branch})")
    # 1. CODEOWNERS — a PR must not be able to disable its OWN gate. Require a code-owner review for any
    #    change to the workflow or the decision store. (Enforced by require_code_owner_reviews below.)
    co = os.path.join(target, ".github", "CODEOWNERS")
    os.makedirs(os.path.dirname(co), exist_ok=True)
    cur = open(co).read() if os.path.exists(co) else ""
    want = [f"/.github/ @{owner}", f"/.precedent/ @{owner}"]
    add = [l for l in want if l.split()[0] not in cur]
    if add:
        with open(co, "a") as f:
            f.write(("\n" if cur and not cur.endswith("\n") else "")
                    + "# Precedent: the gate + the decision store require a code-owner review — a PR can't silently disable its own guardrails.\n"
                    + "\n".join(add) + "\n")
        print(f"  ✓ CODEOWNERS: changes to .github/ and .precedent/ require @{owner} review")
    # 2. make the gate a REQUIRED check + require code-owner review (best-effort; the agent does this)
    body = json.dumps({"required_status_checks": {"strict": True, "contexts": ["govern"]},
                       "enforce_admins": False,
                       "required_pull_request_reviews": {"require_code_owner_reviews": True,
                                                         "required_approving_review_count": 1},
                       "restrictions": None})
    prot = gh("api", "--method", "PUT", f"repos/{slug}/branches/{branch}/protection",
              "--input", "-", input=body)
    if prot.returncode == 0:
        print(f"  ✓ branch protection on {branch}: 'govern' required + code-owner review on the gate/store")
    else:
        print(f"  · couldn't set branch protection automatically (needs admin/paid plan for private repos). To do it:\n"
              f"    gh api --method PUT repos/{slug}/branches/{branch}/protection --input - <<'JSON'\n"
              f"    {body}\n    JSON")
    # 2. the ONE human step: share the secret (the agent must NOT handle the key)
    print("\n  → ONE human step remains — share the model key as a repo secret (you paste it, not the agent):")
    print("      gh secret set OPENROUTER_API_KEY        # get a key at https://openrouter.ai/keys")
    print("    (Only the semantic match/conflict step needs it; the gate's matrix is deterministic.)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    if len(args) != 1:
        sys.exit("usage: python3 src/init.py <target-repo-dir> [--github]")
    main(args[0])
    if "--github" in flags:
        wire_github(os.path.abspath(args[0]))
