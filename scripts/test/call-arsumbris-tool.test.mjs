import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmodSync, closeSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'
import { exchange, openAudit, parseArgs, parseRequest } from '../call-arsumbris-tool.mjs'

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const cli = join(repo, 'scripts/call-arsumbris-tool.mjs')

test('workflow profile keeps core Codex tools and guidance but excludes operator-only market access', () => {
  const codex = readFileSync(join(repo, 'profiles/Keller Codex.yaml'), 'utf8')
  const workflow = readFileSync(join(repo, 'profiles/Keller Workflow.yaml'), 'utf8')
  assert.equal(workflow, codex.replace('mcp.adapter.codex::au-mcp-adapter-codex', 'mcp.adapter.cc::au-mcp-adapter-cc')
    .replace('  - "[[mcp.tool.keller_market]]"\n', ''))
  assert.doesNotMatch(workflow, /mcp\.tool\.keller_market/)
  assert.match(workflow, /nativeToolAllowlist: \[\]/)
})

test('CLI rejects malformed calls and options without echoing private input', () => {
  for (const args of [[], ['--bad'], ['--call', '--timeout-ms', '0'], ['--call', '--timeout-ms', 'NaN'],
    ['--call', '--audit', 'relative.jsonl'], ['--call', '--audit', '/tmp/../private.jsonl']]) {
    assert.throws(() => parseArgs(args))
  }
  for (const text of ['', 'private-password', '{"name":"x"}', '{"name":"x","arguments":[]}',
    '{"name":"x","arguments":{},"other":"secret"}']) assert.throws(() => parseRequest(text))
  const result = spawnSync(process.execPath, [cli, '--call', '--timeout-ms', '0'], {
    input: '{"name":"x","arguments":{"password":"private-password"}}', encoding: 'utf8', cwd: repo,
  })
  assert.equal(result.status, 1)
  assert.equal(result.stdout, '')
  assert.doesNotMatch(result.stderr, /private-password/)
  assert.equal(parseArgs(['--call', '--timeout-ms', '1200000']).timeout, 1200000)
  assert.deepEqual(parseRequest('{"name":"keller_quote","arguments":{"order":{}}}'),
    { name: 'keller_quote', arguments: { order: {} } })
})

test('missing runtime gives actionable category and appends a private failed-attempt trace', t => {
  const root = mkdtempSync(join(tmpdir(), 'keller-mcp-preflight-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const dir = join(root, 'session')
  mkdirSync(dir, { mode: 0o700 })
  const audit = join(dir, 'calls.jsonl')
  const missingRuntime = join(root, 'missing-private-marker-runtime')
  const privateEvidence = 'private-marker-part-drawing'
  const quoteRequest = JSON.stringify({ lines: [{ part_description: 'token-shaped bracket', drawing: privateEvidence }] })
  const run = (mode, input) => spawnSync(process.execPath, [cli, mode, '--runtime-root', missingRuntime, '--audit', audit],
    { input, encoding: 'utf8', cwd: repo })
  const call = run('--call', JSON.stringify({ name: 'keller_quote', arguments: { request: quoteRequest } }))
  const discovery = run('--list', '')
  for (const result of [call, discovery]) {
    assert.equal(result.status, 1)
    assert.match(result.stderr, /\[runtime\].*--runtime-root/)
    assert.doesNotMatch(result.stderr, /private-marker/)
    assert.equal(JSON.parse(result.stdout).error, 'runtime preflight failed')
    assert.doesNotMatch(result.stdout, /private-marker/)
  }
  const rows = readFileSync(audit, 'utf8').trim().split('\n').map(JSON.parse)
  assert.equal(rows.length, 2)
  assert.deepEqual(rows.map(row => row.tool), ['keller_quote', 'tools/list'])
  assert.deepEqual(rows[0].inputs, { request: quoteRequest })
  assert.deepEqual(rows[1].inputs, {})
  for (const row of rows) {
    assert.equal(row.result, null)
    assert.equal(row.error, 'runtime preflight failed')
    assert.ok(Date.parse(row.completedAt) >= Date.parse(row.startedAt))
  }
  assert.equal(lstatSync(audit).mode & 0o777, 0o600)
})

test('credential-bearing fields and DSNs are rejected before opening or appending to audit', t => {
  const root = mkdtempSync(join(tmpdir(), 'keller-mcp-sensitive-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const dir = join(root, 'session')
  mkdirSync(dir, { mode: 0o700 })
  const audit = join(dir, 'calls.jsonl')
  const previous = '{"existing":"private business evidence"}\n'
  writeFileSync(audit, previous, { mode: 0o600 })
  const cases = [
    { name: 'keller_quote', arguments: { reviewer: 'A', db_password: 'private-credential' } },
    { name: 'keller_quote', arguments: { credentials: 'private-credential' } },
    { name: 'keller_quote', arguments: { request: JSON.stringify({ lines: [{ password: 'private-credential' }] }) } },
    { name: 'keller_quote', arguments: { request: '{"lines":[{"pass\\u0077ord":"private-credential"}]}' } },
    { name: 'keller_quote', arguments: { request: JSON.stringify({ lines: [{ source: 'postgresql://user:private-credential@host/db' }] }) } },
    { name: 'keller_polygres', arguments: { note: 'host=db password=private-credential' } },
    { name: 'keller_polygres', arguments: { source: 'jdbc:postgresql://host/db' } },
    { name: 'keller_polygres', arguments: { source: 'postgresql+psycopg://user:private-credential@host/db' } },
  ]
  for (const input of cases) {
    const result = spawnSync(process.execPath, [cli, '--call', '--runtime-root', '/missing/private-marker-runtime', '--audit', audit],
      { input: JSON.stringify(input), encoding: 'utf8', cwd: repo })
    assert.equal(result.status, 1)
    assert.match(result.stderr, /\[input\]/)
    assert.doesNotMatch(result.stderr, /private-credential|private-marker|postgresql:\/\//)
    assert.equal(result.stdout, '')
    assert.equal(readFileSync(audit, 'utf8'), previous)
  }
  assert.deepEqual(parseRequest(JSON.stringify({ name: 'keller_quote', arguments: {
    request: JSON.stringify({ lines: [{ part_description: 'token-shaped stamped bracket', customer: 'private business evidence' }] }),
  } })).arguments.request, JSON.stringify({ lines: [{ part_description: 'token-shaped stamped bracket', customer: 'private business evidence' }] }))
})

test('audit is append-only and rejects unsafe directory, file, and symlink', t => {
  const root = mkdtempSync(join(tmpdir(), 'keller-mcp-audit-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const privateDir = join(root, 'session')
  mkdirSync(privateDir, { mode: 0o700 })
  const path = join(privateDir, 'calls.jsonl')
  let fd = openAudit(path)
  writeFileSync(fd, '{"tool":"first"}\n')
  closeSync(fd)
  fd = openAudit(path)
  writeFileSync(fd, '{"tool":"second"}\n')
  closeSync(fd)
  assert.equal(readFileSync(path, 'utf8').split('\n').length, 3)
  assert.equal(lstatSync(path).mode & 0o777, 0o600)
  chmodSync(path, 0o644)
  assert.throws(() => openAudit(path), /Audit file/)
  chmodSync(path, 0o600)
  symlinkSync(path, join(privateDir, 'linked.jsonl'))
  assert.throws(() => openAudit(join(privateDir, 'linked.jsonl')))
  chmodSync(privateDir, 0o755)
  assert.throws(() => openAudit(path), /Audit directory/)
  chmodSync(privateDir, 0o700)
  symlinkSync(privateDir, join(root, 'linked-dir'))
  assert.throws(() => openAudit(join(root, 'linked-dir', 'calls.jsonl')), /Unsafe audit directory/)
})

test('fake MCP responses preserve complete results and errors in trace without daemon', async () => {
  const records = []
  const request = { name: 'keller_quote', arguments: { order: { part: 'fixture' } } }
  const success = { content: [{ type: 'text', text: '{"state":"PRICED_REQUIRES_REVIEW"}' }] }
  const client = { callTool: async (_input, _schema, options) => {
    assert.deepEqual(_input, request)
    assert.equal(options.timeout, 1200000)
    return success
  } }
  const output = await exchange(client, '--call', request, 1200000, row => records.push(row))
  assert.equal(output.tool, 'keller_quote')
  assert.deepEqual(output.result, success)
  assert.deepEqual(records[0].inputs, request.arguments)
  assert.ok(Date.parse(records[0].completedAt) >= Date.parse(records[0].startedAt))
  assert.equal((await exchange({ callTool: async () => ({ content: [], isError: true }) }, '--call', request, 1, row => records.push(row))).error,
    'MCP tool returned an error')
  assert.deepEqual(records[1].result, { content: [], isError: true })
  const bad = await exchange({ callTool: async () => ({ wrong: 'secret' }) }, '--call', request, 1, row => records.push(row))
  assert.equal(bad.error, 'Invalid MCP tool response')
  assert.deepEqual(bad.result, { wrong: 'secret' })
  const thrown = await exchange({ callTool: async () => { throw new Error('postgresql://private-dsn') } }, '--call', request, 1, row => records.push(row))
  assert.equal(thrown.error, 'MCP request failed')
  assert.doesNotMatch(JSON.stringify(records), /private-dsn/)
})

test('fake MCP discovery returns descriptors and follows pagination', async () => {
  const records = []
  const cursors = []
  const result = await exchange({ listTools: async (params, options) => {
    cursors.push(params?.cursor)
    assert.equal(options.timeout, 500)
    return params?.cursor ? { tools: [{ name: 'keller_quote', inputSchema: {} }] } :
      { tools: [{ name: 'au_files', inputSchema: {} }], nextCursor: 'next' }
  } }, '--list', undefined, 500, row => records.push(row))
  assert.deepEqual(cursors, [undefined, 'next'])
  assert.deepEqual(result.result.tools.map(tool => tool.name), ['au_files', 'keller_quote'])
  assert.deepEqual(records[0].inputs, {})
})
