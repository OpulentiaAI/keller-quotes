import { existsSync, lstatSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { lock, output } from './arsumbris-runtime.mjs'

function gitBytes(cwd, args) {
  const result = spawnSync('git', args, { cwd, stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 16 * 1024 * 1024 })
  if (result.error || result.status !== 0) throw new Error(`Cannot read pinned overlay from Git: ${args[0]}`)
  return result.stdout
}

export function hostOverlay(host, workspace, apply = false) {
  const { commit, path: prefix, fileCount } = lock.hostOverlay
  if (output('git', ['rev-parse', `${commit}^{commit}`], workspace) !== commit) {
    throw new Error(`Missing pinned Keller host overlay commit ${commit}`)
  }
  const paths = output('git', ['ls-tree', '-r', '--name-only', commit, prefix], workspace)
    .split('\n').filter(Boolean).map(path => path.slice(prefix.length + 1))
  if (paths.length !== fileCount || paths.some(path => !path || path.startsWith('/') || path.split('/').includes('..'))) {
    throw new Error('Pinned host overlay has unexpected file paths or count')
  }
  const expected = new Map(paths.map(path => [path, gitBytes(workspace, ['show', `${commit}:${prefix}/${path}`])]))
  const changed = gitBytes(host, ['status', '--porcelain=v1', '--untracked-files=all', '-z']).toString('utf8')
    .split('\0').filter(Boolean)
  for (const entry of changed) {
    const status = entry.slice(0, 2)
    const path = entry.slice(3)
    if (![' M', '??'].includes(status) || !expected.has(path) ||
        !existsSync(join(host, path)) || !readFileSync(join(host, path)).equals(expected.get(path))) {
      throw new Error(`Unexpected local change in pinned host checkout: ${path}`)
    }
  }
  const missing = []
  for (const [path, content] of expected) {
    const target = join(host, path)
    if (existsSync(target) && lstatSync(target).isSymbolicLink()) throw new Error(`Refusing symlinked host overlay target: ${path}`)
    if (existsSync(target) && readFileSync(target).equals(content)) continue
    if (existsSync(target)) {
      const baseline = spawnSync('git', ['show', `HEAD:${path}`], { cwd: host, stdio: ['ignore', 'pipe', 'ignore'] })
      if (baseline.status !== 0 || !readFileSync(target).equals(baseline.stdout)) {
        throw new Error(`Refusing to overwrite host file outside exact overlay: ${path}`)
      }
    }
    missing.push([target, content, existsSync(target)])
  }
  if (!apply && missing.length) throw new Error(`Host overlay incomplete (${missing.length} files); run setup without --register-only`)
  for (const [target, content, existed] of missing) {
    mkdirSync(dirname(target), { recursive: true })
    writeFileSync(target, content, { flag: existed ? 'w' : 'wx' })
  }
  return expected.size
}
