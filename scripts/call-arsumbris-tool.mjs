#!/usr/bin/env node
import { constants, closeSync, fstatSync, lstatSync, openSync, readFileSync, writeSync } from 'node:fs'
import { dirname, isAbsolute, join, parse, resolve, sep } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { options, requireRuntime, requireWorkspace, requireProfile } from './arsumbris-runtime.mjs'

const profileName = 'Keller Workflow'
const usage = 'usage: node scripts/call-arsumbris-tool.mjs <--list|--call> [--runtime-root DIR] [--workspace DIR] [--audit /private/session.jsonl] [--timeout-ms N]'

export function parseArgs(argv) {
  const args = [...argv]
  const mode = args.shift()
  if (!['--list', '--call'].includes(mode)) throw new Error(usage)
  let audit, timeout = 600000
  const runtimeArgs = []
  for (let i = 0; i < args.length; i++) {
    if (['--audit', '--timeout-ms', '--runtime-root', '--workspace'].includes(args[i]) && args[i + 1] && !args[i + 1].startsWith('--')) {
      const key = args[i++], value = args[i]
      if (key === '--audit') {
        if (audit !== undefined) throw new Error(usage)
        audit = value
      } else if (key === '--timeout-ms') {
        if (!/^[1-9]\d*$/.test(value) || !Number.isSafeInteger(Number(value))) throw new Error(usage)
        timeout = Number(value)
      } else runtimeArgs.push(key, value)
    } else throw new Error(usage)
  }
  if (audit !== undefined && (!isAbsolute(audit) || audit.split(sep).includes('..'))) throw new Error('Audit path must be absolute and contain no parent traversal')
  return { mode, audit, timeout, ...options(runtimeArgs) }
}

export function parseRequest(text) {
  let request
  try { request = JSON.parse(text) } catch { throw new Error('Expected one JSON object on stdin') }
  if (!request || Array.isArray(request) || typeof request !== 'object' ||
      Object.keys(request).some(key => !['name', 'arguments'].includes(key)) ||
      typeof request.name !== 'string' || !/^[a-zA-Z][\w-]*$/.test(request.name) ||
      !request.arguments || Array.isArray(request.arguments) || typeof request.arguments !== 'object') {
    throw new Error('Expected {"name":"tool_name","arguments":{...}} on stdin')
  }
  const credentialKey = /(?:password|passwd|pwd|secret|credentials?|token|apikey|accesskey|privatekey|authorization|dsn|connectionstring|connectionurl|databaseurl|directurl|dburl|databaseuri|dburi)$/
  function containsCredential(value, decodeQuoteRequest = false) {
    if (typeof value === 'string') {
      if (/(?:jdbc:)?postgres(?:ql)?(?:\+[a-z0-9_]+)?:\/\/|(?:^|[\s;])password\s*=/i.test(value)) return true
      if (!decodeQuoteRequest) return false
      let decoded
      try { decoded = JSON.parse(value) } catch { throw new Error('Invalid quote request JSON') }
      return containsCredential(decoded)
    }
    if (Array.isArray(value)) return value.some(item => containsCredential(item))
    if (value && typeof value === 'object') {
      return Object.entries(value).some(([key, item]) => {
        const normalizedKey = key.replace(/[^a-z0-9]/gi, '').toLowerCase()
        return normalizedKey === 'auth' || credentialKey.test(normalizedKey) ||
          containsCredential(item, decodeQuoteRequest && key === 'request')
      })
    }
    return false
  }
  if (containsCredential(request.arguments, request.name === 'keller_quote')) throw new Error('Credential-bearing input is not accepted')
  return request
}

export function openAudit(path) {
  const parent = dirname(path)
  if (parent === path || path === parse(path).root) throw new Error('Audit path must name a private file')
  let current = parse(parent).root
  for (const part of parent.slice(current.length).split(sep).filter(Boolean)) {
    current = join(current, part)
    const stat = lstatSync(current)
    if (!stat.isDirectory() || stat.isSymbolicLink() || ![process.getuid(), 0].includes(stat.uid) ||
        ((stat.mode & 0o022) && !(stat.uid === 0 && (stat.mode & 0o1000)))) {
      throw new Error('Unsafe audit directory')
    }
  }
  const dir = lstatSync(parent)
  if (dir.uid !== process.getuid() || (dir.mode & 0o077)) throw new Error('Audit directory must be owner-private (0700)')
  const fd = openSync(path, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o600)
  try {
    const stat = fstatSync(fd)
    if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || (stat.mode & 0o177) || !(stat.mode & 0o200)) {
      throw new Error('Audit file must be owner-private (0600), regular, and unlinked elsewhere')
    }
    return fd
  } catch (error) {
    closeSync(fd)
    throw error
  }
}

export async function exchange(client, mode, request, timeout, record = () => {}) {
  const startedAt = new Date().toISOString()
  const tool = mode === '--list' ? 'tools/list' : request.name
  const inputs = mode === '--list' ? {} : request.arguments
  let result, error
  try {
    if (mode === '--list') {
      const tools = []
      let cursor
      do {
        const page = await client.listTools(cursor ? { cursor } : undefined, { timeout })
        if (!Array.isArray(page?.tools) || page.tools.some(item => typeof item?.name !== 'string')) throw new Error('Invalid MCP tools response')
        tools.push(...page.tools)
        cursor = page.nextCursor
      } while (cursor)
      result = { tools }
    } else {
      result = await client.callTool({ name: tool, arguments: inputs }, undefined, { timeout })
      if (!result || typeof result !== 'object' || !Array.isArray(result.content) ||
          result.content.some(item => !item || typeof item.type !== 'string') ||
          (result.isError !== undefined && typeof result.isError !== 'boolean')) {
        throw new Error('Invalid MCP tool response')
      }
    }
  } catch (cause) {
    error = cause.message === 'Invalid MCP tool response' || cause.message === 'Invalid MCP tools response'
      ? cause.message : 'MCP request failed'
  }
  const entry = { startedAt, completedAt: new Date().toISOString(), tool, inputs, result: result ?? null }
  if (error) entry.error = error
  record(entry)
  const { inputs: _inputs, ...response } = entry
  return { ...response, ...(mode === '--call' && result?.isError ? { error: 'MCP tool returned an error' } : {}) }
}

async function main() {
  let fd, client, mode, request, startedAt
  let stage = 'input'
  try {
    const args = parseArgs(process.argv.slice(2))
    mode = args.mode
    const { audit, timeout, runtimeRoot, workspace } = args
    request = mode === '--call' ? parseRequest(readFileSync(0, 'utf8')) : undefined
    startedAt = new Date().toISOString()
    stage = 'audit'
    if (audit) fd = openAudit(audit)
    stage = 'runtime'
    const root = requireRuntime(runtimeRoot)
    stage = 'workspace'
    const entry = requireWorkspace(workspace)
    stage = 'profile'
    requireProfile(entry, profileName)
    stage = 'client-dependencies'
    const sdkRoot = join(root, 'au-mcp-adapter-cc/node_modules/@modelcontextprotocol/sdk/dist/esm/client')
    const { Client } = await import(pathToFileURL(join(sdkRoot, 'index.js')).href)
    const { StdioClientTransport } = await import(pathToFileURL(join(sdkRoot, 'stdio.js')).href)
    const transport = new StdioClientTransport({ command: process.execPath,
      args: [join(entry, 'scripts/start-arsumbris-mcp-client.mjs'), '--workspace', entry,
        '--runtime-root', root, '--profile', profileName],
      env: { PATH: process.env.PATH, HOME: process.env.HOME } })
    client = new Client({ name: 'keller-workflow-stdio', version: '0' })
    const record = row => { if (fd !== undefined) writeSync(fd, `${JSON.stringify(row)}\n`) }
    let response
    stage = 'connection'
    try {
      await client.connect(transport)
    } catch {
      const row = { startedAt, completedAt: new Date().toISOString(),
        tool: mode === '--list' ? 'tools/list' : request.name,
        inputs: mode === '--list' ? {} : request.arguments, result: null, error: 'MCP connection failed' }
      record(row)
      const { inputs: _inputs, ...withoutInputs } = row
      response = withoutInputs
    }
    stage = 'request'
    if (!response) response = await exchange(client, mode, request, timeout, record)
    console.log(JSON.stringify(response))
    if (response.error) process.exitCode = 1
  } catch {
    const guidance = {
      input: 'invalid options or JSON request; use --list or --call with one JSON object on stdin',
      audit: 'unsafe or unavailable --audit path; use an owner-private directory and file',
      runtime: 'missing or incomplete --runtime-root; pass the pinned installed runtime directory',
      workspace: 'invalid --workspace; pass an Ars workspace entry',
      profile: 'Keller Workflow profile missing or invalid; check the explicit profile',
      'client-dependencies': 'pinned MCP client SDK unavailable under --runtime-root',
      connection: 'MCP connection failed; check the headless engine and MCP services',
      request: 'MCP request or audit write failed',
    }
    if (fd !== undefined && ['runtime', 'workspace', 'profile', 'client-dependencies'].includes(stage)) {
      const row = { startedAt, completedAt: new Date().toISOString(),
        tool: mode === '--list' ? 'tools/list' : request.name,
        inputs: mode === '--list' ? {} : request.arguments, result: null, error: `${stage} preflight failed` }
      try {
        writeSync(fd, `${JSON.stringify(row)}\n`)
        const { inputs: _inputs, ...response } = row
        console.log(JSON.stringify(response))
      } catch {
        stage = 'audit'
      }
    }
    console.error(`Ars MCP caller failed [${stage}]: ${guidance[stage]}`)
    process.exitCode = 1
  } finally {
    await client?.close().catch(() => {})
    if (fd !== undefined) closeSync(fd)
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
