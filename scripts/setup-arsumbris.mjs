#!/usr/bin/env node
import { existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { command, output, checkRepository, lock, options, requireWorkspace } from './arsumbris-runtime.mjs'
import { hostOverlay } from './arsumbris-overlay.mjs'
import { saveMcpConfig } from './arsumbris-mcp-config.mjs'

const args = process.argv.slice(2)
const registerOnly = args.includes('--register-only')
const codexIndex = args.indexOf('--codex-binary')
const codexBinary = codexIndex < 0 ? undefined : args[codexIndex + 1]
if (codexIndex >= 0 && (!codexBinary || codexBinary.startsWith('--'))) {
  console.error('--codex-binary requires an absolute executable path')
  process.exit(2)
}
if (codexIndex >= 0) args.splice(codexIndex, 2)
const opts = options(args.filter(arg => arg !== '--register-only'))
const { runtimeRoot, workspace, deviceRoot } = opts

try {
  requireWorkspace(workspace)
  const nodeMajor = Number(process.versions.node.split('.')[0])
  if (nodeMajor < 23 || nodeMajor >= 26) throw new Error('Ars requires Node >=23 and <26 (Node 24 LTS recommended)')
  if (!registerOnly) {
    mkdirSync(runtimeRoot, { recursive: true })
    for (const [name, sha] of Object.entries(lock.repositories)) {
      const path = join(runtimeRoot, name)
      if (!existsSync(path)) {
        command('git', ['clone', '--branch', lock.release, '--no-checkout', `${lock.upstream}/${name}.git`, path], runtimeRoot)
        command('git', ['checkout', '--detach', sha], path)
      }
      const dirty = checkRepository(path, name, sha)
      if (dirty && name !== 'au-host') throw new Error(`Unexpected local changes in ${name}; refusing to build an unpinned source tree`)
    }
    console.log(`Verified ${hostOverlay(join(runtimeRoot, 'au-host'), workspace, true)} exact Keller host overlay files`)
    const pinnedPnpm = output('pnpm', ['--version'], join(runtimeRoot, 'au-host'))
    if (pinnedPnpm !== '11.1.1') throw new Error(`Expected pnpm 11.1.1, found ${pinnedPnpm}`)
    for (const name of ['au-engine-sdk', 'au-mcp', 'au-mcp-sdk', 'au-mcp-core', 'au-mcp-adapter-cc', 'au-mcp-adapter-codex', 'au-type-codegen', 'au-host']) {
      command('pnpm', ['install', '--frozen-lockfile'], join(runtimeRoot, name))
    }
    command('cargo', ['build', '--release', '--locked', '-j2'], join(runtimeRoot, 'au-engine'))
    const host = join(runtimeRoot, 'au-host')
    command('pnpm', ['--filter', 'app', 'exec', 'install-electron'], host)
    command('pnpm', ['--filter', 'app', 'rebuild:native'], host)
    command('pnpm', ['-r', '--workspace-concurrency=2', 'build'], host)
    command('pnpm', ['--filter', 'app', 'build:shared-deps'], host)
    const venv = join(workspace, '.keller-local/arsumbris/python')
    if (!existsSync(join(venv, 'bin/python'))) command('python3', ['-m', 'venv', venv], workspace)
    command(join(venv, 'bin/python'), ['-m', 'pip', 'install', '-r', join(workspace, 'requirements-db.txt'), 'psycopg[binary]==3.3.6', 'dbfread==2.0.7'], workspace)
    command('npm', ['ci'], join(workspace, 'estimator'))
    command('npm', ['run', 'build'], join(workspace, 'estimator'))
  } else {
    for (const [name, sha] of Object.entries(lock.repositories)) {
      const dirty = checkRepository(join(runtimeRoot, name), name, sha)
      if (dirty && name !== 'au-host') throw new Error(`Unexpected local changes in ${name}; refusing registration`)
    }
    hostOverlay(join(runtimeRoot, 'au-host'), workspace)
  }
  const pinnedPnpm = output('pnpm', ['--version'], join(runtimeRoot, 'au-host'))
  if (pinnedPnpm !== '11.1.1') throw new Error(`Expected pnpm 11.1.1, found ${pinnedPnpm}`)
  const registration = [join(workspace, 'scripts/register-arsumbris.py'), '--runtime-root', runtimeRoot, '--workspace', workspace, '--device-root', deviceRoot, '--node', process.execPath]
  if (codexBinary) registration.push('--codex-binary', codexBinary)
  command('python3', registration, workspace)
  command('python3', [...registration, '--write'], workspace)
  console.log(`MCP client config: ${saveMcpConfig(workspace, runtimeRoot)}`)
  console.log(`Ars runtime ready at ${runtimeRoot}; workspace registered at ${workspace}`)
} catch (error) {
  console.error(`Ars setup failed: ${error.message}`)
  process.exitCode = 1
}
