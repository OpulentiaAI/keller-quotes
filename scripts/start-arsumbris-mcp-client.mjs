#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'
import { options, requireProfile, requireRuntime, requireWorkspace } from './arsumbris-runtime.mjs'

const argv = process.argv.slice(2)
const profileIndex = argv.indexOf('--profile')
if (profileIndex < 0 || !argv[profileIndex + 1]) {
  console.error('usage: node scripts/start-arsumbris-mcp-client.mjs --profile <scoped-CC-profile-name> [--runtime-root DIR] [--workspace DIR]')
  process.exit(2)
}
const profileName = argv[profileIndex + 1]
argv.splice(profileIndex, 2)
let transport
let child
try {
  const { runtimeRoot, workspace } = options(argv)
  const root = requireRuntime(runtimeRoot)
  const entry = requireWorkspace(workspace)
  const profile = requireProfile(entry, profileName)
  const engineSdk = await import(pathToFileURL(join(root, 'au-engine-sdk/src/index.ts')).href)
  const engine = await engineSdk.DaemonClient.connect(entry)
  try {
    const frame = await engine.read({ read: 'instances_of', type: 'agent-profile' })
    const rows = frame.result?.instances_of
    const selected = Array.isArray(rows) && rows.find(row => row.path === profile)
    if (frame.ready !== true || !selected || !Array.isArray(selected.fields?.tools) || selected.fields.tools.length === 0 ||
        !Array.isArray(selected.fields?.nativeToolAllowlist) || selected.fields.nativeToolAllowlist.length !== 0) {
      throw new Error(`Scoped profile ${profileName} is not resolved in the ready engine graph; refusing unrestricted MCP launch`)
    }
  } finally {
    engine.close()
  }
  const sdk = await import(pathToFileURL(join(root, 'au-mcp-sdk/src/index.ts')).href)
  const { ccAdapterInfo } = await import(pathToFileURL(join(root, 'au-mcp-adapter-cc/src/surface.ts')).href)
  transport = await sdk.connectSocket(sdk.socketPath(entry))
  const client = sdk.createDaemonClient(transport)
  const handle = randomUUID()
  const session = randomUUID()
  try {
    await client.sessionOpen(ccAdapterInfo(session, entry, handle, false, profile))
    child = spawn(process.execPath, [join(root, 'au-mcp-adapter-cc/bin/mcp-server.ts')], {
      cwd: entry, stdio: 'inherit', env: { PATH: process.env.PATH, HOME: process.env.HOME,
        AU_MCP_WORKSPACE: entry, AU_MCP_SESSION: handle, AU_MCP_PROFILE: profile },
    })
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
    const result = await new Promise((resolve, reject) => {
      child.on('error', reject)
      child.on('exit', (code, signal) => resolve(code ?? (signal ? 128 + (signal === 'SIGINT' ? 2 : 15) : 1)))
    })
    process.exitCode = result
  } finally {
    await client.sessionClose(session).catch(error => console.error(`Ars session close failed: ${error.message}`))
    client.dispose()
  }
} catch (error) {
  console.error(`Ars MCP client failed: ${error.message}`)
  process.exitCode = 1
} finally {
  transport?.close()
}
