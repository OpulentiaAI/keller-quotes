#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { options, requireRuntime, requireWorkspace } from './arsumbris-runtime.mjs'

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
  const learningPython = join(entry, '.keller-local/learning/python/bin/python')
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
      KELLER_PYTHON: process.env.KELLER_PYTHON ?? (existsSync(learningPython) ? learningPython : join(entry, '.keller-local/arsumbris/python/bin/python')),
    } : {}),
    ...(service === 'host' ? { AU_ENTRY: entry } : {}),
  }
  const child = spawn(target.binary, target.args, {
    cwd: target.cwd, stdio: 'inherit', env,
  })
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
  child.on('error', error => { console.error(error.message); process.exitCode = 1 })
  child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 128 + (signal === 'SIGINT' ? 2 : 15) : 1) })
} catch (error) {
  console.error(`Ars launch failed: ${error.message}`)
  process.exitCode = 1
}
