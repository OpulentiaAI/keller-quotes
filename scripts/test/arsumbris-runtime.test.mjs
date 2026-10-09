import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'
import { checkRepository, lock, options, requireProfile } from '../arsumbris-runtime.mjs'
import { hostOverlay } from '../arsumbris-overlay.mjs'
import { mcpConfig, saveMcpConfig } from '../arsumbris-mcp-config.mjs'

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..')

test('lock records every pinned sibling at a full SHA', () => {
  assert.equal(Object.keys(lock.repositories).length, 22)
  assert.equal(lock.repositories['au-host'], 'eb736c500a1474b1f77711720d774488e386d616')
  for (const sha of Object.values(lock.repositories)) assert.match(sha, /^[0-9a-f]{40}$/)
  assert.equal(options(['--runtime-root', '/some/other/runtime']).runtimeRoot, '/some/other/runtime')
})

test('existing checkouts are never reset, including dirty or wrong-revision clones', t => {
  const root = mkdtempSync(join(tmpdir(), 'ars-repo-check-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const run = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
  run('init', '-q')
  run('config', 'user.email', 'fixture@example.invalid')
  run('config', 'user.name', 'Test fixture')
  run('remote', 'add', 'origin', 'https://github.com/arsumbris/au-engine.git')
  writeFileSync(join(root, 'tracked'), 'base')
  run('add', 'tracked')
  run('commit', '-qm', 'fixture')
  const sha = run('rev-parse', 'HEAD')
  assert.equal(checkRepository(root, 'au-engine', sha), false)
  writeFileSync(join(root, 'tracked'), 'user change')
  assert.equal(checkRepository(root, 'au-engine', sha), true)
  assert.equal(readFileSync(join(root, 'tracked'), 'utf8'), 'user change')
  assert.throws(() => checkRepository(root, 'au-engine', '0'.repeat(40)), /refusing to change/)
  assert.throws(() => checkRepository(root, 'au-host', sha), /Unexpected origin/)
})

test('scoped profile required and unprofiled or Codex profile rejected', t => {
  const root = mkdtempSync(join(tmpdir(), 'ars-profile-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  mkdirSync(join(root, 'profiles'))
  assert.throws(() => requireProfile(root, 'Missing'), /Missing scoped profile/)
  writeFileSync(join(root, 'profiles', 'Read.yaml'), 'adapter: "[[mcp.adapter.codex::au-mcp-adapter-codex]]"\ntools:\n  - "[[mcp.tool.read_file_pinned]]"\nnativeToolAllowlist: []\n')
  assert.throws(() => requireProfile(root, 'Read'), /target CC/)
  writeFileSync(join(root, 'profiles', 'Read.yaml'), 'adapter: "[[mcp.adapter.cc::au-mcp-adapter-cc]]"\ntools:\n  - "[[mcp.tool.read_file_pinned]]"\nnativeToolAllowlist: []\n')
  assert.equal(requireProfile(root, 'Read'), join(root, 'profiles', 'Read.yaml'))
})

test('local MCP config uses absolute paths and preserves user edits', t => {
  const root = mkdtempSync(join(tmpdir(), 'ars-mcp-config-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const expected = mcpConfig(root, '/other/runtime', process.execPath)
  assert.deepEqual(Object.keys(expected.mcpServers), ['keller-ars-readonly', 'keller-polygres-readonly'])
  for (const entry of Object.values(expected.mcpServers)) {
    assert.equal(entry.command, process.execPath)
    assert.ok(entry.args.includes('/other/runtime'))
    assert.ok(!JSON.stringify(entry).includes('POLYGRES_DIRECT_URL'))
  }
  const path = saveMcpConfig(root, '/other/runtime')
  assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')), expected)
  assert.equal(saveMcpConfig(root, '/other/runtime'), path)
  writeFileSync(path, '{"user":"edited"}')
  assert.throws(() => saveMcpConfig(root, '/other/runtime'), /preserving user file/)
  assert.equal(readFileSync(path, 'utf8'), '{"user":"edited"}')
})

test('pinned 25-file overlay applies only over clean baseline and refuses foreign changes', t => {
  const host = mkdtempSync(join(tmpdir(), 'ars-overlay-'))
  t.after(() => rmSync(host, { recursive: true, force: true }))
  const tracked = ['app/src/renderer/src/main.tsx', 'packages/au-host-launcher/src/Welcome.tsx',
    'packages/au-host-launcher/src/css.d.ts', 'packages/au-host-launcher/src/welcome.css',
    'packages/style/default-theme.ts', 'packages/style/ext.css', 'packages/style/fonts.css']
  for (const path of tracked) {
    mkdirSync(dirname(join(host, path)), { recursive: true })
    writeFileSync(join(host, path), 'clean upstream baseline')
  }
  const run = (...args) => execFileSync('git', args, { cwd: host, stdio: ['ignore', 'pipe', 'pipe'] })
  run('init', '-q'); run('config', 'user.email', 'fixture@example.invalid'); run('config', 'user.name', 'Test fixture'); run('add', '.'); run('commit', '-qm', 'fixture')
  assert.throws(() => hostOverlay(host, repo), /overlay incomplete/)
  assert.equal(hostOverlay(host, repo, true), 25)
  assert.equal(hostOverlay(host, repo), 25)
  writeFileSync(join(host, 'unrelated-user-file'), 'keep')
  assert.throws(() => hostOverlay(host, repo, true), /Unexpected local change/)
  rmSync(join(host, 'unrelated-user-file'))
  writeFileSync(join(host, tracked[0]), 'custom user change')
  assert.throws(() => hostOverlay(host, repo, true), /Unexpected local change/)
  assert.equal(readFileSync(join(host, tracked[0]), 'utf8'), 'custom user change')
})

test('registration merges runtime and nested workspace paths without clobbering existing entries', t => {
  const root = mkdtempSync(join(tmpdir(), 'ars-register-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const runtime = join(root, 'runtime'), workspace = join(root, 'workspace'), device = join(root, 'device')
  mkdirSync(join(runtime, 'arsumbris/scripts'), { recursive: true })
  writeFileSync(join(runtime, 'arsumbris/scripts/seed-device-config.py'), `
import os
def discover_repos(root):
    found = []
    for directory, dirs, files in os.walk(root):
        if '.arsumbris' in dirs:
            path = os.path.join(directory, '.arsumbris', 'repo.yaml')
            if os.path.isfile(path):
                found.append((open(path).read().split('name: ')[1].strip(), directory, None))
    return found
def yaml_scalar(value): return value
def parse_repos_yaml(path):
    if not os.path.isfile(path): return {}
    pairs = {}
    lines = open(path).read().splitlines()
    for i, line in enumerate(lines):
        if '- name:' in line: pairs[line.split(': ', 1)[1]] = lines[i + 1].split(': ', 1)[1]
    return pairs
def parse_template_repos(path):
    if not os.path.isfile(path): return []
    return [line.split(': ', 1)[1] for line in open(path) if '- path:' in line]
def existing_top_keys(path):
    if not os.path.isfile(path): return set()
    return {line.split(':', 1)[0] for line in open(path) if line and line[0].isalpha()}
`)
  for (const path of ['au-engine/target/release', 'au-mcp/src', 'au-defaults', 'au-host/packages/typed/.arsumbris']) mkdirSync(join(runtime, path), { recursive: true })
  writeFileSync(join(runtime, 'au-engine/target/release/au'), '')
  writeFileSync(join(runtime, 'au-mcp/src/cli.ts'), '')
  writeFileSync(join(runtime, 'au-host/packages/typed/.arsumbris/repo.yaml'), 'name: typed\n')
  for (const path of ['.arsumbris', 'type/typed-keller/.arsumbris']) mkdirSync(join(workspace, path), { recursive: true })
  writeFileSync(join(workspace, '.arsumbris/repo.yaml'), 'name: keller-quotes\n')
  writeFileSync(join(workspace, 'type/typed-keller/.arsumbris/repo.yaml'), 'name: typed-keller\n')
  const registry = join(device, 'au-engine/config/repos.yaml')
  mkdirSync(dirname(registry), { recursive: true })
  writeFileSync(registry, '# keep this user note\nrepos:\n  - name: personal\n    path: /my/repo\n')
  const args = [join(repo, 'scripts/register-arsumbris.py'), '--runtime-root', runtime, '--workspace', workspace, '--device-root', device, '--node', process.execPath]
  const run = (...extra) => spawnSync('python3', [...args, ...extra], { encoding: 'utf8' })
  assert.equal(run().status, 0)
  assert.equal(readFileSync(registry, 'utf8').split('\n').length, 5)
  assert.equal(run('--write').status, 0)
  const first = readFileSync(registry, 'utf8')
  assert.match(first, /# keep this user note/)
  assert.match(first, /name: typed-keller/)
  assert.match(first, /name: typed/)
  assert.match(first, /name: personal/)
  assert.equal(run('--write').status, 0)
  assert.equal(readFileSync(registry, 'utf8'), first)
  writeFileSync(registry, first.replace('path: /my/repo', 'path: /my/repo').replace(`path: ${workspace}`, 'path: /other/location'))
  assert.match(run('--write').stderr, /refusing to replace/)
})
