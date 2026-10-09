#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { options, requireRuntime, requireWorkspace } from './arsumbris-runtime.mjs'

export async function prepareHostEngine({ entry, binary, env, sdk, spawnChild = spawn, wait = delay, now = Date.now, timeoutMs = 120_000 }) {
  let child
  let failure
  let cancelled = false
  const stop = signal => {
    cancelled = true
    child?.kill(signal)
  }
  const interrupt = () => stop('SIGINT')
  const terminate = () => stop('SIGTERM')
  process.on('SIGINT', interrupt)
  process.on('SIGTERM', terminate)
  try {
    const initial = await sdk.probeReady(entry)
    if (initial?.ready) return null
    const pid = sdk.readDaemonPid(entry)
    if (!initial && !(pid !== null && sdk.pidAlive(pid))) {
      child = spawnChild(binary, ['daemon', 'start', entry], { cwd: entry, stdio: 'inherit', env })
      child.on('error', error => { failure = error })
      child.on('exit', (code, signal) => { failure = new Error(`Engine exited before readiness (${signal ?? code})`) })
    }
    const deadline = now() + timeoutMs
    while (now() < deadline) {
      if (cancelled) throw new Error('Host startup cancelled')
      if (failure) throw failure
      const ready = await sdk.probeReady(entry)
      if (cancelled) throw new Error('Host startup cancelled')
      if (failure) throw failure
      if (ready?.ready) return child ?? null
      await wait(500)
    }
    throw new Error(`Engine did not become ready within ${timeoutMs / 1000}s; host not launched`)
  } catch (error) {
    child?.kill('SIGTERM')
    throw error
  } finally {
    process.removeListener('SIGINT', interrupt)
    process.removeListener('SIGTERM', terminate)
  }
}

// Operator-only preflight; never pass these bindings to engine or blinded worker processes.
export function operatorBindings(entry, source = process.env) {
  const localPython = join(entry, '.keller-local/arsumbris/python/bin/python')
  const python = source.KELLER_PYTHON || (existsSync(localPython) ? localPython : 'python3')
  const env = Object.fromEntries(['HOME', 'PATH', 'LANG', 'LC_ALL'].filter(key => source[key] !== undefined).map(key => [key, source[key]]))
  env.KELLER_SOURCE_CONFIG = source.KELLER_SOURCE_CONFIG || join(entry, '.keller-local/arsumbris/sources.json')
  const probe = spawnSync(python, ['-B', '-c', 'import sys; print(sys.executable)'], { env, encoding: 'utf8', timeout: 10000 })
  if (probe.error || probe.status !== 0 || !probe.stdout.trim().startsWith('/')) throw new Error('Executable Python unavailable; set KELLER_PYTHON to an installed interpreter')
  const executable = probe.stdout.trim()
  const check = spawnSync(executable, ['-B', join(entry, 'arsumbris/sources/read.py')], {
    input: '{"action":"sets"}', env, encoding: 'utf8', timeout: 10000, maxBuffer: 8192,
  })
  let result
  try { result = JSON.parse(check.stdout) } catch {}
  if (check.error || check.status !== 0 || !Array.isArray(result?.source_sets) || result.error ||
      !result.source_sets.some(set => set.configured)) throw new Error('Owner source configuration/roots unavailable; set approved KELLER_SOURCE_CONFIG before operator launch')
  return { KELLER_SOURCE_CONFIG: env.KELLER_SOURCE_CONFIG, KELLER_PYTHON: executable }
}

export function engineEnvironment(env) {
  const operatorKeys = ['POLYGRES_DIRECT_URL', 'KELLER_PYTHON', 'KELLER_SOURCE_CONFIG', 'AU_ENTRY',
    'KELLER_MARKET_ENABLED', 'EXA_API_KEY', 'FASTMARKETS_ACCESS_TOKEN', 'KELLER_FASTMARKETS_LICENSED']
  return Object.fromEntries(Object.entries(env).filter(([key]) => !operatorKeys.includes(key)))
}

async function main() {
  const [service, ...args] = process.argv.slice(2)
  if (!['engine', 'mcp', 'host'].includes(service)) {
    console.error('usage: node scripts/start-arsumbris.mjs <engine|mcp|host> [--runtime-root DIR] [--workspace DIR] [--software-rendering (host)]')
    process.exit(2)
  }
  try {
    const software = args.includes('--software-rendering')
    const { runtimeRoot, workspace } = options(args.filter(arg => arg !== '--software-rendering'))
    if (software && service !== 'host') throw new Error('--software-rendering applies only to host')
    const root = requireRuntime(runtimeRoot)
    const entry = requireWorkspace(workspace)
    const target = {
      engine: { binary: join(root, 'au-engine/target/release/au'), args: ['daemon', 'start', entry], cwd: entry },
      mcp: { binary: process.execPath, args: [join(root, 'au-mcp/src/cli.ts'), 'start', entry], cwd: entry },
      host: { binary: join(root, 'au-host/app/node_modules/.bin/electron'), args: [join(root, 'au-host/app/out/main/index.js'), ...(software ? ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [])], cwd: join(root, 'au-host') },
    }[service]
    const env = { PATH: process.env.PATH, HOME: process.env.HOME, LANG: process.env.LANG,
      DISPLAY: process.env.DISPLAY, XAUTHORITY: process.env.XAUTHORITY, XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR,
      DBUS_SESSION_BUS_ADDRESS: process.env.DBUS_SESSION_BUS_ADDRESS, WAYLAND_DISPLAY: process.env.WAYLAND_DISPLAY,
      SHELL: process.env.SHELL, USER: process.env.USER, TERM: process.env.TERM,
      ...(service === 'host' || service === 'mcp' ? {
        POLYGRES_DIRECT_URL: process.env.POLYGRES_DIRECT_URL,
        KELLER_MARKET_ENABLED: process.env.KELLER_MARKET_ENABLED,
        EXA_API_KEY: process.env.EXA_API_KEY,
        FASTMARKETS_ACCESS_TOKEN: process.env.FASTMARKETS_ACCESS_TOKEN,
        KELLER_FASTMARKETS_LICENSED: process.env.KELLER_FASTMARKETS_LICENSED,
        ...operatorBindings(entry),
      } : {}),
      ...(service === 'host' ? { AU_ENTRY: entry } : {}),
    }
    let engine
    if (service === 'host') {
      const sdk = await import(pathToFileURL(join(root, 'au-engine-sdk/src/client.ts')).href)
      console.log('Preparing the native workspace graph before opening the host (up to 120s).')
      const engineEnv = engineEnvironment(env)
      engine = await prepareHostEngine({ entry, binary: join(root, 'au-engine/target/release/au'), env: engineEnv, sdk })
    }
    const child = spawn(target.binary, target.args, {
      cwd: target.cwd, stdio: 'inherit', env,
    })
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { child.kill(signal); engine?.kill(signal) })
    child.on('error', error => { engine?.kill('SIGTERM'); console.error(error.message); process.exitCode = 1 })
    child.on('exit', (code, signal) => { engine?.kill('SIGTERM'); process.exitCode = code ?? (signal ? 128 + (signal === 'SIGINT' ? 2 : 15) : 1) })
  } catch (error) {
    console.error(`Ars launch failed: ${error.message}`)
    process.exitCode = 1
  }
}

if (resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) await main()
