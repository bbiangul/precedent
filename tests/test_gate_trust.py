"""The gate must judge a PR with the base branch's engine and decisions, never with code from the PR.

A PR can edit `src/govern_cli.py` or `.precedent/decisions.json`. If the gate runs the PR's checkout, that
PR decides its own verdict. This builds such a PR (the engine rewritten to always allow, plus a change the
seed decisions send to review) and runs the gate step in the checkout its workflow prescribes.
"""
import os, re, shutil, subprocess, tempfile, unittest

from test_workflows import ROOT, run_blocks

GATE = os.path.join(ROOT, ".github", "workflows", "precedent-gate.yml")
STEP = "Run govern(diff)"


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    *args], cwd=repo, check=True, capture_output=True)


def step_script(workflow):
    start = workflow.index(f"name: {STEP}")
    return next(run_blocks(workflow[start:]))


def checks_out_pr_code(workflow):
    """pull_request checks out the PR; pull_request_target checks out the base unless a checkout pins a ref."""
    if not re.search(r"^\s*pull_request_target:", workflow, re.M):
        return True
    lines = workflow.splitlines()
    for i, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip(" -"))
        for nxt in lines[i + 1:]:
            if nxt.strip() and (len(nxt) - len(nxt.lstrip(" ")) < indent or nxt.lstrip().startswith("- ")):
                break
            if re.match(r"^\s*ref:", nxt):
                return True
    return False


class GateTrust(unittest.TestCase):
    def test_a_pr_that_rewrites_the_gate_is_still_judged_by_the_base(self):
        with open(GATE) as f:
            workflow = f.read()
        work = tempfile.mkdtemp(prefix="gate-trust-")
        self.addCleanup(shutil.rmtree, work, True)
        repo = os.path.join(work, "repo")
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "base")
        git(repo, "checkout", "-q", "-b", "attack")
        cli = os.path.join(repo, "src", "govern_cli.py")
        with open(cli) as f:
            original = f.read()
        with open(cli, "w") as f:
            f.write("import sys\nprint('allowed')\nsys.exit(0)\n" + original)
        os.makedirs(os.path.join(repo, "web"), exist_ok=True)
        with open(os.path.join(repo, "web", "store.ts"), "w") as f:
            f.write('import { createStore } from "redux";\n')
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "attack")
        git(repo, "branch", "pr-head", "attack")
        git(repo, "branch", "-f", "origin-main", "main")
        git(repo, "update-ref", "refs/remotes/origin/main", "main")
        git(repo, "checkout", "-q", "attack" if checks_out_pr_code(workflow) else "main")

        output = os.path.join(work, "github_output")
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": output, "GITHUB_BASE_REF": "main",
               "PR_TITLE": "Add a store"}
        subprocess.run(["bash", "-c", step_script(workflow)], cwd=repo, env=env, capture_output=True, timeout=120)
        with open(output) as f:
            allow = re.search(r"allow=(\d+)", f.read()).group(1)
        self.assertNotEqual(allow, "0", "the PR's own engine decided the verdict")


if __name__ == "__main__":
    unittest.main()
