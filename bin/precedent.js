#!/usr/bin/env node
/* Thin Node launcher so the Python engine is one `npx precedent-cli ...` away.
 * Bundles the engine (src/) + templates; shells out to python3 (stdlib only, no pip deps). */
'use strict'
const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const PKG = path.join(__dirname, '..')
const BUNDLED = path.join(PKG, 'src')

function python() {
  for (const c of [process.env.PRECEDENT_PYTHON, 'python3', 'python']) {
    if (c && spawnSync(c, ['--version'], { stdio: 'ignore' }).status === 0) return c
  }
  console.error('Precedent needs Python 3.9+ on PATH (the engine is Python, stdlib-only). Install it, or set PRECEDENT_PYTHON.')
  process.exit(1)
}

function repoRoot(start) {                       // nearest ancestor with a .precedent/ dir
  let d = start
  for (;;) {
    if (fs.existsSync(path.join(d, '.precedent'))) return d
    const p = path.dirname(d)
    if (p === d) return null
    d = p
  }
}

// prefer the vendored engine (has the repo's config); else the bundled one, told where the repo is
function engineScript(name) {
  const root = repoRoot(process.cwd())
  const vendored = root && path.join(root, '.precedent', 'engine', name)
  if (vendored && fs.existsSync(vendored)) return { script: vendored, root }
  return { script: path.join(BUNDLED, name), root: root || process.cwd() }
}

function run(script, args, root) {
  const env = { ...process.env }
  if (root) env.PRECEDENT_REPO_ROOT = root
  process.exit(spawnSync(python(), [script, ...args], { stdio: 'inherit', env }).status ?? 1)
}

const [cmd, ...rest] = process.argv.slice(2)
const SCRIPTS = { retrieve: 'precedent.py', record: 'precedent.py', deprecate: 'precedent.py',
  'confirm-deprecation': 'precedent.py', govern: 'govern_cli.py', hygiene: 'hygiene.py',
  outcome: 'outcome.py', verify: 'verify.py', sync: 'sync.py' }

if (cmd === 'init') {
  const flags = rest.filter(a => a.startsWith('-'))
  const target = rest.find(a => !a.startsWith('-')) || process.cwd()
  run(path.join(BUNDLED, 'init.py'), [target, ...flags], null)
} else if (cmd in SCRIPTS) {
  const file = SCRIPTS[cmd]
  const { script, root } = engineScript(file)
  // precedent.py takes the subcommand as arg1 (retrieve/record/deprecate/...); others don't
  const args = file === 'precedent.py' ? [cmd, ...rest] : rest
  run(script, args, root)
} else {
  console.log(`Precedent — the decision layer for AI agents (https://precedent.sh)

Usage:
  npx precedent-cli init [dir] [--github]      vendor the engine + AGENTS.md/CLAUDE.md/skill/MCP/CI; --github wires the CI gate
  npx precedent-cli retrieve "<situation>"     decisions that apply before you act
  npx precedent-cli govern --paths <f> --title "<change>"   autonomy verdict at the merge gate
  npx precedent-cli record "<situation; decided X; because Y; scope paths>"
  npx precedent-cli deprecate <id> [--reason R] [--superseded-by ID] [--apply]
  npx precedent-cli hygiene [--propose]        batch: contradictions + stale decisions
`)
  process.exit(cmd ? 1 : 0)
}
