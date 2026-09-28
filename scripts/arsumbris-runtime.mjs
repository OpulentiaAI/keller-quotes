import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

export const workspaceDefault = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const runtimeDefault = join(homedir(), 'arsumbris')
export const lock = JSON.parse(readFileSync(join(workspaceDefault, 'arsumbris/runtime-lock.json'), 'utf8'))

export function options(argv) {
  const out = { workspace: workspaceDefault, runtimeRoot: process.env.ARSUMBRIS_RUNTIME_ROOT ?? runtimeDefault, deviceRoot: join(homedir(), '.arsumbris') }
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i]
    if (!['--workspace', '--runtime-root', '--device-root'].includes(key) || !argv[i + 1] || argv[i + 1].startsWith('--')) {
      throw new Error(`Unknown or incomplete argument: ${key}`)
    }
    out[key === '--runtime-root' ? 'runtimeRoot' : key === '--device-root' ? 'deviceRoot' : 'workspace'] = resolve(argv[++i])
  }
  out.workspace = resolve(out.workspace)
  out.runtimeRoot = resolve(out.runtimeRoot)
  out.deviceRoot = resolve(out.deviceRoot)
  return out
}

export function command(binary, args, cwd, extra = {}) {
  const result = spawnSync(binary, args, { cwd, stdio: 'inherit', env: { ...process.env, ...extra } })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${binary} ${args[0] ?? ''} failed (${result.status ?? result.signal})`)
}

export function output(binary, args, cwd) {
  const result = spawnSync(binary, args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`${binary} ${args.join(' ')} failed: ${result.stderr.trim()}`)
  return result.stdout.trim()
}

export function checkRepository(path, name, sha, run = output) {
  if (!existsSync(join(path, '.git'))) throw new Error(`Refusing to replace existing non-git directory: ${path}`)
  const remote = run('git', ['remote', 'get-url', 'origin'], path)
  if (!new RegExp(`^(https://(github\\.com|git\\.capy\\.ai)/arsumbris/|git@github\\.com:arsumbris/)${name}\\.git$`).test(remote)) {
    throw new Error(`Unexpected origin for ${path}; refusing to use this checkout`)
  }
  const head = run('git', ['rev-parse', 'HEAD'], path)
  if (head !== sha) throw new Error(`${name} is at ${head}, expected ${sha}; refusing to change an existing checkout`)
  return run('git', ['status', '--porcelain'], path) !== ''
}

export function requireWorkspace(path) {
  const canonical = realpathSync(path)
  if (!existsSync(join(canonical, '.arsumbris/repo.yaml')) || !existsSync(join(canonical, '.arsumbris/workspace.yaml'))) {
    throw new Error(`Not an Ars workspace entry: ${canonical}`)
  }
  return canonical
}

export function requireRuntime(path) {
  for (const name of ['au-engine', 'au-mcp', 'au-host']) {
    if (!existsSync(join(path, name))) throw new Error(`Missing runtime repository ${name} under ${path}; run setup-arsumbris first`)
  }
  return realpathSync(path)
}

export function requireProfile(workspace, profile) {
  if (!profile || profile.includes('/') || profile.includes('\\') || profile === '.' || profile === '..') throw new Error('Pass a local profile name with --profile')
  const path = join(workspace, 'profiles', `${profile}.yaml`)
  if (!existsSync(path)) throw new Error(`Missing scoped profile: ${path}`)
  const text = readFileSync(path, 'utf8')
  if (!/^adapter:.*mcp\.adapter\.cc::au-mcp-adapter-cc/m.test(text) ||
      !/^tools:\s*\n\s+-\s+"?\[\[/m.test(text) ||
      !/^nativeToolAllowlist:\s*\[\s*\]\s*$/m.test(text)) {
    throw new Error(`Profile ${profile} must target CC, explicitly allow tools, and deny native tools`)
  }
  return path
}
