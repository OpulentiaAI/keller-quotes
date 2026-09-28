import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { exchange, openAudit, parseArgs } from '../call-arsumbris-tool.mjs'
import { loadEvaluationScope, sameDecimal } from '../mcp-evaluation-scope.mjs'

const root = resolve(import.meta.dirname, '../..')
const cli = join(root, 'scripts/call-arsumbris-tool.mjs')
const sha = 'a'.repeat(64), pdf = 'b'.repeat(64), transcript = 'c'.repeat(64)
const row = { quote_no: 'SAFE', item_no: '1', quantity: '3', unit_price: '1.23456', extended_price: '3.70',
  quote_date: '2024-01-01', letter_date: '2024-01-02', date_stamp: '', part_no: 'P', customer_id: 'C',
  source_price_field: 'PRICE', price_basis: 'customer_quote_pdf', status: 'unknown', source_path: 'synthetic/safe.pdf',
  pdf_sha256: pdf, transcript_sha256: transcript }
const request = { order_id: 'ORDER', quote_date: '2025-01-01', customer: 'Synthetic', customer_id: 'C', reviewer: 'Casey',
  parts: [{ line_id: 'L1', part_no: 'P', quantity: 3 }], charges: { shipping: 1.25, tax: 0 } }
const skill = join(root, '.agents/skills/keller-quote-estimator/SKILL.md')
const publicContracts = ['docs/pricing-evals-and-orders.md', 'estimator/src/order.ts', 'estimator/src/types.ts'].map(path => join(root, path))

function fixture(t, transform = x => x) {
  const dir = mkdtempSync(join(tmpdir(), 'mcp-scope-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const privateDir = join(dir, 'private')
  mkdirSync(privateDir, { mode: 0o700 })
  const path = join(privateDir, 'scope.json')
  const scope = transform({ schema_version: 1, case_id: 'synthetic-case', corpus: sha, quote_date: '2025-01-01',
    excluded_quote_nos: ['TARGET'], request: structuredClone(request), eligible_prices: [structuredClone(row)], allowed_files: [skill] })
  writeFileSync(path, JSON.stringify(scope), { mode: 0o600 })
  return { path, privateDir, scope, guard: () => loadEvaluationScope(path, root) }
}

const envelope = payload => ({ content: [{ type: 'text', text: JSON.stringify(payload) }] })
const price = value => ({ row: Object.fromEntries(Object.entries(value).filter(([key]) => !['source_path', 'pdf_sha256', 'transcript_sha256', 'date_stamp'].includes(key))),
  source_path: value.source_path, pdf_sha256: value.pdf_sha256, transcript_sha256: value.transcript_sha256 })
const evidence = (action, extras) => ({ action, corpus: sha, ...extras })
const call = (guard, name, args, handler, records = []) => exchange({ callTool: async input => handler(input) }, '--call',
  { name, arguments: args }, 1000, event => records.push(event), guard)

test('scope validates private regular immutable file, canonical allowlist, and exact decimals', t => {
  const f = fixture(t)
  const guard = f.guard()
  assert.match(guard.sha256, /^[a-f0-9]{64}$/)
  assert.equal(guard.sha256, createHash('sha256').update(readFileSync(f.path)).digest('hex'))
  assert.ok(sameDecimal('1.234560', 1.23456))
  assert.ok(!sameDecimal('1.23456000001', 1.23456))
  writeFileSync(f.path, JSON.stringify({ ...f.scope, case_id: 'different' }))
  assert.throws(() => guard.verify(), /changed/)
  assert.throws(() => parseArgs(['--call', '--evaluation-scope', f.path]))
  assert.equal(parseArgs(['--list', '--audit', join(f.privateDir, 'audit.jsonl'), '--evaluation-scope', f.path]).evaluationScope, f.path)
  chmodSync(f.path, 0o644)
  assert.throws(() => f.guard())
  chmodSync(f.path, 0o600)
  symlinkSync(f.path, join(f.privateDir, 'linked.json'))
  assert.throws(() => loadEvaluationScope(join(f.privateDir, 'linked.json'), root))
  chmodSync(f.privateDir, 0o755)
  assert.throws(() => f.guard())
})

test('malformed scope and nonprior, excluded, duplicate or forged source rows fail closed', t => {
  for (const modify of [
    x => { x.schema_version = 2 }, x => { x.eligible_prices[0].quote_no = 'TARGET' },
    x => { x.eligible_prices[0].quote_date = x.quote_date }, x => { x.eligible_prices[0].letter_date = '2026-01-01' },
    x => { x.eligible_prices[0].date_stamp = '2025-01-01' }, x => { x.eligible_prices[0].pdf_sha256 = 'wrong' },
    x => { x.eligible_prices[0].status = 'won' }, x => { x.eligible_prices[0].price_basis = 'internal_quote_calculation' },
    x => { x.eligible_prices[0].source_price_field = 'cost' }, x => { x.eligible_prices.push(x.eligible_prices[0]) },
    x => { x.allowed_files = ['/etc/passwd'] }, x => { x.request.charges.extra = 1 },
  ]) {
    const f = fixture(t, x => { modify(x); return x })
    assert.throws(() => f.guard())
  }
})

test('empty item numbers retain distinct quantity breaks and exact decimal-equivalent lookups', async t => {
  const f = fixture(t, scope => {
    scope.eligible_prices = [
      { ...row, item_no: '', quantity: '3.000', unit_price: '1.23456' },
      { ...row, item_no: '', quantity: '5.00', unit_price: '1.11111', extended_price: '5.56' },
    ]
    return scope
  })
  const guard = f.guard()
  assert.equal(guard.prices.size, 2)
  const args = { action: 'prices', corpus: sha, part_no: 'P' }
  const breaks = [price({ ...f.scope.eligible_prices[0], quantity: 3 }), price({ ...f.scope.eligible_prices[1], quantity: '5.0' })]
  const result = await call(guard, 'keller_polygres', args, () => envelope(evidence('prices', {
    basis: 'verified issued customer quotation PDF', outcome: 'unknown', prices: breaks, has_more: false, next_offset: null,
  })))
  assert.deepEqual(JSON.parse(result.result.content[0].text).prices, breaks)
  const duplicate = fixture(t, scope => {
    scope.eligible_prices = [{ ...row, item_no: '', quantity: '3' }, { ...row, item_no: '', quantity: 3.0 }]
    return scope
  })
  assert.throws(() => duplicate.guard(), /Conflicting eligible evidence/)
})

test('only the three named public contracts supplement canonical skills', async t => {
  const f = fixture(t, scope => { scope.allowed_files.push(...publicContracts); return scope })
  const guard = f.guard()
  for (const file_path of [skill, ...publicContracts]) {
    const result = await call(guard, 'read_file_pinned', { file_path }, () => envelope({ public: 'synthetic' }))
    assert.ok(result.result)
  }
  const forbidden = await call(guard, 'read_file_pinned', { file_path: join(root, 'docs/mcp-workflow-evaluations.md') },
    () => { throw new Error('should not call backend') })
  assert.equal(forbidden.result, null)
})

test('discovery advertises only guarded tools and every scoped audit row binds the scope hash', async t => {
  const guard = fixture(t).guard(), records = []
  const out = await exchange({ listTools: async () => ({ tools: ['keller_quote', 'keller_polygres', 'au_files', 'read_file_pinned'].map(name =>
    name === 'keller_polygres' ? { name, description: 'Synthetic public tool', inputSchema: { type: 'object', properties: {
      action: { type: 'string' }, limit: { type: 'integer', minimum: 1 }, offset: { type: 'integer', minimum: 0 },
      page_number: { type: 'integer', minimum: 1 },
    } } } : { name }) }) },
    '--list', undefined, 10, event => records.push(event), guard)
  assert.deepEqual(out.result.tools.map(item => item.name), ['keller_quote', 'keller_polygres', 'read_file_pinned'])
  const descriptor = out.result.tools.find(item => item.name === 'keller_polygres')
  assert.match(descriptor.description, /prices\/search limit 1\.\.50.*page limit 1\.\.4000/)
  assert.equal(descriptor.inputSchema.allOf[0].then.properties.limit.maximum, 50)
  assert.equal(descriptor.inputSchema.allOf[1].then.properties.limit.maximum, 4000)
  assert.equal(out.evaluation_scope_sha256, guard.sha256)
  assert.equal(records[0].evaluation_scope_sha256, guard.sha256)
  let calls = 0
  const blocked = await call(guard, 'au_files', {}, () => { calls++; return envelope({ private: 'hidden' }) }, records)
  assert.equal(calls, 0)
  assert.equal(blocked.result, null)
  assert.equal(blocked.evaluation_scope_sha256, guard.sha256)
  assert.equal(records[1].result, null)
  const file = await call(guard, 'read_file_pinned', { file_path: skill }, () => envelope({ skill: 'synthetic allowed read' }), records)
  assert.equal(file.result.content[0].text, '{"skill":"synthetic allowed read"}')
  const audit = join(fixture(t).privateDir, 'audit.jsonl'), fd = openAudit(audit)
  try { await exchange({ callTool: async () => { throw new Error('secret backend failure') } }, '--call',
    { name: 'au_diagnostics', arguments: { limit: 1 } }, 1, event => writeFileSync(fd, JSON.stringify(event) + '\n'), guard) } finally { (await import('node:fs')).closeSync(fd) }
  assert.doesNotMatch(readFileSync(audit, 'utf8'), /secret backend failure/)
  assert.equal(JSON.parse(readFileSync(audit, 'utf8')).evaluation_scope_sha256, guard.sha256)
})

test('scoped CLI preflight failure records only a hash-bound safe result', t => {
  const f = fixture(t), audit = join(f.privateDir, 'trace.jsonl')
  const run = spawnSync(process.execPath, [cli, '--list', '--evaluation-scope', f.path, '--audit', audit,
    '--runtime-root', join(f.privateDir, 'absent-runtime')], { encoding: 'utf8', cwd: root })
  assert.equal(run.status, 1)
  const result = JSON.parse(run.stdout), event = JSON.parse(readFileSync(audit, 'utf8'))
  assert.equal(result.evaluation_scope_sha256, f.guard().sha256)
  assert.equal(event.evaluation_scope_sha256, result.evaluation_scope_sha256)
  assert.equal(event.result, null)
  assert.equal(event.error, 'runtime preflight failed')
})

test('scoped CLI rejects audit aliases before appending or starting runtime', t => {
  for (const alias of [path => path, path => `${dirname(path)}/./scope.json`, path => `${dirname(path)}//scope.json`]) {
    const f = fixture(t)
    const audit = alias(f.path)
    const original = readFileSync(f.path)
    const originalHash = createHash('sha256').update(original).digest('hex')
    const run = spawnSync(process.execPath, [cli, '--list', '--evaluation-scope', f.path, '--audit', audit,
      '--runtime-root', join(f.privateDir, 'absent-runtime')], { encoding: 'utf8', cwd: root })
    assert.equal(run.status, 1)
    assert.equal(run.stdout, '')
    assert.match(run.stderr, /\[audit\]/)
    assert.doesNotMatch(run.stderr, /synthetic-case|absent-runtime|scope\.json/)
    assert.deepEqual(readFileSync(f.path), original)
    assert.equal(createHash('sha256').update(readFileSync(f.path)).digest('hex'), originalHash)
    assert.equal(f.guard().sha256, originalHash)
  }
})

test('selected corpus, excluded pages and selectors are refused before backend calls', async t => {
  const guard = fixture(t).guard()
  let calls = 0
  for (const args of [
    { action: 'prices', corpus: 'd'.repeat(64), part_no: 'P' },
    { action: 'prices', corpus: sha, quote_no: 'TARGET' },
    { action: 'search', corpus: sha, query: 'P', quote_no: 'TARGET' },
    { action: 'page', corpus: sha, source_path: 'synthetic/target.pdf', page_number: 1 },
  ]) {
    const output = await call(guard, 'keller_polygres', args, () => { calls++; return envelope({}) })
    assert.equal(output.result, null)
  }
  assert.equal(calls, 0)
})

test('pagination validation gives fixed actionable errors without weakening scope denial', async t => {
  const guard = fixture(t).guard(), records = []
  let calls = 0
  const success = evidence('prices', { basis: 'verified issued customer quotation PDF', outcome: 'unknown',
    prices: [price(row)], has_more: false, next_offset: null })
  const backend = () => { calls++; return envelope(success) }
  const args = { action: 'prices', corpus: sha, quote_no: 'SAFE', limit: 100 }
  const invalid = await call(guard, 'keller_polygres', args, backend, records)
  assert.equal(calls, 0)
  assert.equal(invalid.error_code, 'INVALID_PAGINATION_ARGUMENTS')
  assert.equal(invalid.error, 'prices/search limit must be an integer from 1 to 50')
  assert.equal(invalid.result, null)
  assert.equal(records[0].error_code, invalid.error_code)
  const corrected = await call(guard, 'keller_polygres', { ...args, limit: 50 }, backend, records)
  assert.equal(calls, 1)
  assert.equal(corrected.error, undefined)
  assert.deepEqual(JSON.parse(corrected.result.content[0].text).prices, [price(row)])
  const pageArgs = { action: 'page', corpus: sha, source_path: row.source_path, page_number: 1, limit: 4000 }
  const page = evidence('page', { source_path: row.source_path, page_number: 1, page_count: 1,
    pdf_sha256: pdf, page_sha256: sha, kind: 'quote', basis: 'PDF page text; not verified numeric price',
    text: 'synthetic', has_more: false, next_offset: null })
  const pageOK = await call(guard, 'keller_polygres', pageArgs, () => { calls++; return envelope(page) }, records)
  assert.equal(pageOK.error, undefined)
  assert.equal(calls, 2)
  const pageTooLarge = await call(guard, 'keller_polygres', { ...pageArgs, limit: 4001 }, backend, records)
  assert.equal(pageTooLarge.error_code, 'INVALID_PAGINATION_ARGUMENTS')
  assert.equal(pageTooLarge.error, 'page limit must be an integer from 1 to 4000')
  assert.equal(calls, 2)
  const denied = await call(guard, 'keller_polygres', { ...args, quote_no: 'TARGET', limit: 100 }, backend, records)
  assert.equal(denied.error_code, 'EVALUATION_SCOPE_DENIED')
  assert.equal(denied.error, 'Evaluation scope denied this request')
  assert.equal(calls, 2)
  assert.doesNotMatch(JSON.stringify(records), /TARGET.*limit must be an integer/)
})

test('prices remove target, future, forged amounts and hashes while preserving backend pagination', async t => {
  const guard = fixture(t).guard()
  const args = { action: 'prices', corpus: sha, part_no: 'P', limit: 2, offset: 0 }
  const target = price({ ...row, quote_no: 'TARGET' })
  const future = price({ ...row, quote_no: 'FUTURE', quote_date: '2026-01-01' })
  const data = evidence('prices', { basis: 'verified issued customer quotation PDF', outcome: 'unknown',
    prices: [target, future], has_more: true, next_offset: 2 })
  const output = await call(guard, 'keller_polygres', args, () => envelope(data))
  assert.deepEqual(JSON.parse(output.result.content[0].text).prices, [])
  assert.equal(JSON.parse(output.result.content[0].text).next_offset, 2)
  for (const candidate of [price({ ...row, unit_price: '1.23457' }), price({ ...row, pdf_sha256: 'd'.repeat(64) })]) {
    const result = await call(guard, 'keller_polygres', args, () => envelope({ ...data, prices: [candidate, price(row)] }))
    assert.deepEqual(JSON.parse(result.result.content[0].text).prices, [price(row)])
  }
})

test('search filters document identity; page verifies quote kind, path and hash', async t => {
  const guard = fixture(t).guard(), args = { action: 'search', corpus: sha, query: 'synthetic', limit: 2 }
  const hit = { source_path: row.source_path, page_number: 1, page_sha256: sha, pdf_sha256: pdf, kind: 'quote', excerpt: 'text' }
  const output = await call(guard, 'keller_polygres', args, () => envelope(evidence('search', { basis: 'PDF page text; not verified numeric price',
    hits: [{ ...hit, source_path: 'synthetic/target.pdf' }, hit], has_more: true, next_offset: 2 })))
  assert.deepEqual(JSON.parse(output.result.content[0].text).hits, [hit])
  const page = { action: 'page', corpus: sha, source_path: row.source_path, page_number: 1, page_count: 2,
    pdf_sha256: pdf, page_sha256: sha, kind: 'quote', basis: 'PDF page text; not verified numeric price',
    text: 'not price authority', has_more: false, next_offset: null }
  const pageArgs = { action: 'page', corpus: sha, source_path: row.source_path, page_number: 1 }
  assert.deepEqual(JSON.parse((await call(guard, 'keller_polygres', pageArgs, () => envelope(page))).result.content[0].text), page)
  for (const change of [{ kind: 'invoice' }, { pdf_sha256: sha }, { source_path: 'synthetic/target.pdf' }, { page_number: 3 }]) {
    const rejected = await call(guard, 'keller_polygres', pageArgs, () => envelope({ ...page, ...change }))
    assert.equal(rejected.result, null)
  }
})

test('quote identity, reviewer, date, parts and charges are exact, but proposals may vary', async t => {
  const guard = fixture(t).guard()
  const submitted = { ...structuredClone(request), parts: [{ ...request.parts[0], pricing: { method: 'unit_price', unit_price: 1.2333, reason: 'synthetic' } }], notes: 'draft' }
  const inputs = { corpus: sha, reviewer: 'Casey', request: JSON.stringify(submitted) }
  const analog = { quote_no: 'SAFE', quote_date: row.quote_date, date_stamp: '', letter_date: row.letter_date,
    part_no: 'P', status: 'unknown', price_evidence: { price_basis: 'customer_quote_pdf', source_document: row.source_path,
      source_document_sha256: pdf, source_transcript_sha256: transcript, source_price_field: 'PRICE' } }
  const requestSha = createHash('sha256').update(JSON.stringify(submitted)).digest('hex')
  const makeDraft = (state, analogs) => ({ state, corpus_id: sha, corpus_sha256: pdf, request_sha256: requestSha, reviewer: 'Casey',
    review: { state, corpus_id: sha, corpus_sha256: pdf, request_sha256: requestSha, reviewer: 'Casey',
      status: 'PENDING_NAMED_HUMAN_REVIEW', requires_human_review: true, customer_release_authorized: false },
    order: { state, order_id: 'ORDER', quote_date: request.quote_date, customer: 'Synthetic', request: submitted,
      provenance: { as_of: request.quote_date, request_sha256: requestSha, register_sha256: pdf }, requires_human_review: true,
      lines: [{ line_id: 'L1', part: { part_no: 'P', quantity: 3 }, analogs }],
      charges: request.charges, additional_charges: [] }, requires_human_review: true, markdown: `synthetic ${state}` })
  let calls = 0
  for (const changed of [
    { corpus: 'd'.repeat(64) }, { reviewer: 'Other' },
    { request: JSON.stringify({ ...submitted, quote_date: '2026-01-01' }) },
    { request: JSON.stringify({ ...submitted, parts: [{ ...submitted.parts[0], quantity: 4 }] }) },
    { request: JSON.stringify({ ...submitted, charges: { shipping: 9, tax: 0 } }) },
    { request: JSON.stringify({ ...submitted, additional_charges: [{ label: 'fee', amount: 1 }] }) },
  ]) {
    const result = await call(guard, 'keller_quote', { ...inputs, ...changed }, () => { calls++; return envelope(makeDraft('BLOCKED', [])) })
    assert.equal(result.result, null)
  }
  assert.equal(calls, 0)
  for (const state of ['BLOCKED', 'PRICED_REQUIRES_REVIEW']) {
    const draft = envelope(makeDraft(state, [analog]))
    const output = await call(guard, 'keller_quote', inputs, () => draft)
    assert.deepEqual(output.result, draft)
  }
  for (const changed of [{ quote_no: 'TARGET' }, { quote_date: '2026-01-01' },
    { price_evidence: { ...analog.price_evidence, source_document_sha256: sha } }]) {
    const output = await call(guard, 'keller_quote', inputs, () => envelope(makeDraft('BLOCKED', [{ ...analog, ...changed }])))
    assert.equal(output.result, null)
  }
  for (const mutate of [
    draft => { draft.review.reviewer = 'Other' },
    draft => { draft.review.request_sha256 = sha },
    draft => { draft.review.customer_release_authorized = true },
    draft => { draft.order.request.quote_date = '2026-01-01' },
    draft => { draft.order.request.parts[0].part_no = 'OTHER' },
    draft => { draft.order.charges.shipping = 99 },
    draft => { draft.order.provenance.as_of = '2026-01-01' },
  ]) {
    const draft = makeDraft('BLOCKED', [])
    mutate(draft)
    assert.equal((await call(guard, 'keller_quote', inputs, () => envelope(draft))).result, null)
  }
})

test('malformed and alternate MCP content channels never enter scoped audit', async t => {
  const guard = fixture(t).guard(), records = []
  const args = { action: 'prices', corpus: sha, part_no: 'P' }
  for (const backend of [
    { content: [{ type: 'text', text: 'secret' }], structuredContent: { secret: 'raw' } },
    { content: [{ type: 'text', text: '{}' }, { type: 'text', text: 'secret' }] },
    { content: [{ type: 'resource', resource: { text: 'secret' } }] },
    { content: [{ type: 'text', text: 'private error' }], isError: true },
    { content: [{ type: 'text', text: '{"action":"prices"}' }] },
    { content: [{ type: 'text', text: '{}' }], extra: 'secret' },
  ]) {
    const output = await call(guard, 'keller_polygres', args, () => backend, records)
    assert.equal(output.result, null)
    assert.equal(records.at(-1).result, null)
  }
  assert.doesNotMatch(JSON.stringify(records), /secret|private error|raw/)
})
