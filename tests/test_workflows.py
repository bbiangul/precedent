"""Workflow shell steps must not interpolate attacker-controlled event fields.

A `${{ github.event.pull_request.title }}` inside `run:` is pasted into the shell before it runs, so a PR
titled `x"; curl … $OPENROUTER_API_KEY; "` executes in the step that holds the secret. Pass such values
through `env:` and quote the variable instead.
"""
import glob, os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import init  # noqa: E402

UNTRUSTED = re.compile(r"\$\{\{\s*github\.(event\.|head_ref)")


def run_blocks(text):
    """Yield the script of every `run:` key, inline or as an indented block."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2)
        if rest and rest[0] not in "|>":
            yield rest
            continue
        block = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt)
        yield "\n".join(block)


class WorkflowInjection(unittest.TestCase):
    def assert_no_untrusted_in_run(self, name, text):
        for script in run_blocks(text):
            self.assertIsNone(UNTRUSTED.search(script), f"{name}: event field interpolated in run:\n{script}")

    def test_repository_workflows(self):
        files = glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))
        self.assertTrue(files)
        for path in files:
            with open(path) as f:
                self.assert_no_untrusted_in_run(os.path.basename(path), f.read())

    def test_workflow_that_init_installs(self):
        self.assert_no_untrusted_in_run("init._WORKFLOW", init._WORKFLOW)

    def test_detector_catches_the_pattern(self):
        bad = 'jobs:\n  a:\n    steps:\n      - run: |\n          echo "${{ github.event.pull_request.title }}"\n'
        self.assertEqual(len([s for s in run_blocks(bad) if UNTRUSTED.search(s)]), 1)


if __name__ == "__main__":
    unittest.main()
