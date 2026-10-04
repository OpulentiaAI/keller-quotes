import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, existsSync, linkSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { KnowledgeStore } from '../keller-knowledge.mjs'

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const cli = join(checkout, 'scripts/keller-knowledge.mjs')
const hash = value => createHash('sha256').update(value).digest('hex')
const clone = value => JSON.parse(JSON.stringify(value))
const query = { workflow: 'quoting', as_of: '2026-10-04' }
const operator = { operator: 'Casey Operator', reason: 'Reviewed the unchanged scoped guidance and both private reports.',
  development_report_sha256: 'd'.repeat(64), confirmation_report_sha256: 'c'.repeat(64) }

function fixture(t, count = 1) {
  const work = join(homedir(), '.capy', 'work')
  mkdirSync(work, { recursive: true, mode: 0o700 })
  const privateDir = mkdtempSync(join(work, 'keller-knowledge-test-'))
  chmodSync(privateDir, 0o700)
  t.after(() => rmSync(privateDir, { recursive: true, force: true }))
  const root = join(privateDir, 'knowledge'), sourceDir = join(privateDir, 'sources')
  mkdirSync(root, { mode: 0o700 })
  mkdirSync(sourceDir, { mode: 0o700 })
  const source = join(sourceDir, 'operator-observation.txt')
  const bytes = 'Observed source: confirm the drawing revision before quoting.\nThe specified finish is satin.\n'
  writeFileSync(source, bytes, { mode: 0o600 })
  const packet = { packet_id: 'packet-1', generator_id: 'generator-1', candidates: Array.from({ length: count }, (_, index) => ({
    index, kind: 'procedure', topic: 'drawing-revision', statement: 'Confirm the drawing revision before quoting.', scope: { workflow: `quoting${index || ''}` },
    evidence: [{ path: source, sha256: hash(bytes), excerpt: 'confirm the drawing revision before quoting.', authority: 'tool_observation' }],
    valid_from: '2026-10-01', valid_until: '2026-12-31',
  })) }
  const store = new KnowledgeStore(root)
  const review = (staged, verdicts = packet.candidates.map(candidate => ({ index: candidate.index, verdict: 'ACCEPT', reason: 'Supported by the cited observation.' }))) => ({
    packet_sha256: staged.packet_sha256, reviewer_id: 'reviewer-1', verdicts,
  })
  const accept = (p = packet) => {
    const staged = store.stage(p)
    const reviewed = store.review(p.packet_id, review(staged, p.candidates.map(candidate => ({ index: candidate.index, verdict: 'ACCEPT', reason: 'Supported by the cited observation.' }))))
    return { staged, reviewed }
  }
  return { privateDir, root, sourceDir, source, bytes, packet, store, review, accept }
}

function throwsCode(fn, code) {
  assert.throws(fn, error => error.code === code)
}

function run(action, root, input, args = []) {
  const result = spawnSync(process.execPath, [cli, action, '--root', root, ...args], {
    input: typeof input === 'string' || Buffer.isBuffer(input) ? input : JSON.stringify(input), encoding: 'utf8', cwd: checkout, maxBuffer: 300 * 1024,
  })
  assert.equal(result.error, undefined)
  assert.equal(result.stderr, '')
  assert.ok(Buffer.byteLength(result.stdout) <= 256 * 1024)
  return { ...result, output: JSON.parse(result.stdout) }
}

function eventPaths(root) {
  return readdirSync(join(root, 'events')).sort().map(file => join(root, 'events', file))
}

function replaceImmutable(path, bytes) {
  chmodSync(path, 0o600)
  writeFileSync(path, bytes)
  chmodSync(path, 0o400)
}

test('stage is immutable and idempotent, review does not promote, and attestation binds all hashes', t => {
  const f = fixture(t)
  const staged = f.store.stage(f.packet)
  assert.equal(staged.status, 'STAGED')
  assert.equal(staged.idempotent, false)
  assert.match(staged.packet_sha256, /^[a-f0-9]{64}$/)
  assert.deepEqual(f.store.search(query).records, [])
  const once = eventPaths(f.root)
  assert.deepEqual(f.store.stage(clone(f.packet)), { ...staged, idempotent: true })
  assert.deepEqual(eventPaths(f.root), once)
  const changed = clone(f.packet)
  changed.candidates[0].statement = 'Changed statement.'
  throwsCode(() => f.store.stage(changed), 'PACKET_ID_CONFLICT')
  throwsCode(() => f.store.activate(f.packet.packet_id, 0, operator), 'REVIEW_REQUIRED')
  const reviewed = f.store.review(f.packet.packet_id, f.review(staged))
  assert.equal(reviewed.status, 'REVIEWED')
  assert.equal(reviewed.verdicts[0].verdict, 'ACCEPT')
  assert.deepEqual(f.store.search(query).records, [])
  throwsCode(() => f.store.activate(f.packet.packet_id, 0, {}), 'INVALID_SCHEMA')
  const activated = f.store.activate(f.packet.packet_id, 0, operator)
  assert.equal(activated.status, 'ACTIVE')
  const result = new KnowledgeStore(f.root, { readOnly: true }).search(query)
  assert.equal(result.usage, 'reference_only')
  assert.equal(result.blind_safety, 'NOT_ATTESTED')
  assert.equal(result.records.length, 1)
  const record = result.records[0]
  assert.equal(record.record_id, activated.record_id)
  assert.equal(record.record_sha256, activated.record_sha256)
  assert.equal(record.packet_sha256, staged.packet_sha256)
  assert.equal(record.review_sha256, reviewed.review_sha256)
  assert.deepEqual(record.operator_attestation, operator)
  assert.deepEqual(record.scope, f.packet.candidates[0].scope)
  assert.equal(record.evidence[0].sha256, hash(readFileSync(record.evidence[0].copied_path)))
  assert.equal(record.evidence[0].path, f.source)
  assert.equal(record.evidence[0].authority, 'tool_observation')
  assert.equal(lstatSync(record.evidence[0].copied_path).mode & 0o777, 0o400)
  for (const path of eventPaths(f.root)) {
    assert.equal(lstatSync(path).mode & 0o777, 0o400)
    assert.ok(path.endsWith(`${hash(readFileSync(path))}.json`))
  }
  for (const name of ['events', 'evidence']) assert.equal(lstatSync(join(f.root, name)).mode & 0o777, 0o700)
  throwsCode(() => f.store.review(f.packet.packet_id, f.review(staged)), 'REVIEW_ALREADY_RECORDED')
  throwsCode(() => f.store.activate(f.packet.packet_id, 0, operator), 'CANDIDATE_ALREADY_DISPOSED')
  assert.equal(existsSync(join(f.root, '.writer.lock')), false)
})

test('mutating caller objects or key order cannot alter a staged or active record', t => {
  const f = fixture(t)
  const original = clone(f.packet)
  const staged = f.store.stage(f.packet)
  const reordered = Object.fromEntries(Object.entries(original).reverse())
  assert.equal(f.store.stage(reordered).packet_sha256, staged.packet_sha256)
  f.packet.candidates[0].statement = 'Caller-side mutation.'
  const submittedReview = f.review(staged)
  f.store.review(original.packet_id, submittedReview)
  submittedReview.verdicts[0].verdict = 'REJECT'
  const attested = clone(operator)
  f.store.activate(original.packet_id, 0, attested)
  attested.operator = 'Changed operator'
  const first = f.store.search(query)
  assert.equal(first.records[0].statement, original.candidates[0].statement)
  assert.deepEqual(first.records[0].operator_attestation, operator)
  first.records[0].statement = 'Changed search result.'
  assert.equal(f.store.search(query).records[0].statement, original.candidates[0].statement)
})

test('missing, duplicate, conflicting, lowercase, and malformed verdicts reject affected candidates', t => {
  const attempts = [
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }],
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }, { index: 1, verdict: 'ACCEPT', reason: 'One.' }, { index: 1, verdict: 'ACCEPT', reason: 'Two.' }],
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }, { index: 1, verdict: 'ACCEPT', reason: 'One.' }, { index: 1, verdict: 'REJECT', reason: 'Two.' }],
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }, { index: 1, verdict: 'accept', reason: 'Lowercase.' }],
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }, { index: 1, verdict: 'ACCEPT', reason: '' }],
    [{ index: 0, verdict: 'ACCEPT', reason: 'Supported.' }, { index: 1, verdict: 'ACCEPT', reason: 'Supported.', extra: true }],
  ]
  for (const verdicts of attempts) {
    const f = fixture(t, 3), staged = f.store.stage(f.packet)
    const reviewed = f.store.review(f.packet.packet_id, f.review(staged, verdicts))
    assert.deepEqual(reviewed.verdicts.map(item => item.verdict), ['ACCEPT', 'REJECT', 'REJECT'])
    throwsCode(() => f.store.activate(f.packet.packet_id, 1, operator), 'CANDIDATE_REJECTED')
    throwsCode(() => f.store.activate(f.packet.packet_id, 2, operator), 'CANDIDATE_REJECTED')
    f.store.activate(f.packet.packet_id, 0, operator)
    throwsCode(() => f.store.review(f.packet.packet_id, f.review(staged)), 'REVIEW_ALREADY_RECORDED')
  }
})

test('review failures reject the complete batch permanently, including self-review and wrong hash', t => {
  const failedReviews = [
    () => null,
    () => undefined,
    () => 'Reviewer timeout',
    (f, staged) => ({ ...f.review(staged), reviewer_id: f.packet.generator_id }),
    (f, staged) => ({ ...f.review(staged), reviewer_id: f.packet.generator_id.toUpperCase() }),
    (f, staged) => ({ ...f.review(staged), packet_sha256: 'a'.repeat(64) }),
    (f, staged) => ({ ...f.review(staged), unexpected: true }),
    (f, staged) => ({ ...f.review(staged), verdicts: [] }),
    (f, staged) => ({ ...f.review(staged), verdicts: [{ verdict: 'ACCEPT', reason: 'No index.' }] }),
    (f, staged) => ({ ...f.review(staged), verdicts: [{ index: 9, verdict: 'ACCEPT', reason: 'Unknown index.' }] }),
    (f, staged) => ({ ...f.review(staged), verdicts: 'Not an array' }),
  ]
  for (const submission of failedReviews) {
    const f = fixture(t, 2), staged = f.store.stage(f.packet)
    const reviewed = f.store.review(f.packet.packet_id, submission(f, staged))
    assert.equal(reviewed.status, 'REVIEW_FAILED')
    assert.deepEqual(reviewed.verdicts.map(item => item.verdict), ['REJECT', 'REJECT'])
    assert.deepEqual(f.store.search(query).records, [])
    throwsCode(() => f.store.activate(f.packet.packet_id, 0, operator), 'CANDIDATE_REJECTED')
    throwsCode(() => new KnowledgeStore(f.root).review(f.packet.packet_id, f.review(staged)), 'REVIEW_ALREADY_RECORDED')
  }
})

test('empty candidate batches and all-rejected reviews are valid without any active records', t => {
  const empty = fixture(t, 0), staged = empty.store.stage(empty.packet)
  assert.deepEqual(empty.store.search(query).records, [])
  assert.equal(eventPaths(empty.root).length, 1)
  const reviewed = empty.store.review(empty.packet.packet_id, empty.review(staged, []))
  assert.equal(staged.candidate_count, 0)
  assert.equal(reviewed.status, 'REVIEWED')
  assert.deepEqual(reviewed.verdicts, [])
  assert.deepEqual(empty.store.search(query).records, [])
  const f = fixture(t), populated = f.store.stage(f.packet)
  assert.equal(f.store.review(f.packet.packet_id, f.review(populated, [{ index: 0, verdict: 'REJECT', reason: 'Insufficient support.' }])).status, 'REVIEWED')
  throwsCode(() => f.store.activate(f.packet.packet_id, 0, operator), 'CANDIDATE_REJECTED')
})

test('search requires exact declared scope, complete business context, and inclusive valid dates', t => {
  const f = fixture(t)
  Object.assign(f.packet.candidates[0], { kind: 'specification', scope: {
    workflow: 'quoting', customer_id: 'CUSTOMER-A', part_no: 'PART-A', revision: 'R1', material: 'steel',
  } })
  f.accept()
  f.store.activate(f.packet.packet_id, 0, operator)
  const exact = { ...query, ...f.packet.candidates[0].scope }
  assert.equal(f.store.search(exact).records.length, 1)
  for (const key of ['customer_id', 'part_no', 'revision', 'material']) {
    const missing = { ...exact }
    delete missing[key]
    assert.deepEqual(f.store.search(missing).records, [])
    assert.deepEqual(f.store.search({ ...exact, [key]: `${exact[key]}-other` }).records, [])
  }
  assert.deepEqual(f.store.search({ ...exact, workflow: 'Quoting' }).records, [])
  for (const as_of of ['2026-09-30', '2027-01-01']) assert.deepEqual(f.store.search({ ...exact, as_of }).records, [])
  for (const as_of of ['2026-10-01', '2026-12-31']) assert.equal(f.store.search({ ...exact, as_of }).records.length, 1)
  throwsCode(() => f.store.search({ ...exact, as_of: '2026-02-30' }), 'INVALID_DATE')
  throwsCode(() => f.store.search({ workflow: 'quoting' }), 'INVALID_SCHEMA')
  throwsCode(() => f.store.search({ ...exact, status: 'STAGED' }), 'INVALID_SCHEMA')
  throwsCode(() => f.store.search({ ...exact, limit: 11 }), 'INVALID_LIMIT')
  throwsCode(() => f.store.search({ ...exact, limit: 0 }), 'INVALID_LIMIT')
  throwsCode(() => f.store.search({ ...exact, limit: '1' }), 'INVALID_LIMIT')
})

test('procedures match supplied extra context and query limits never exceed ten records', t => {
  const f = fixture(t)
  const context = { customer_id: 'C', part_no: 'P', revision: 'R', material: 'M' }, keys = Object.keys(context)
  for (let batch = 0; batch < 2; batch++) {
    const packet = clone(f.packet)
    packet.packet_id = `scope-batch-${batch}`
    packet.candidates = Array.from({ length: batch ? 6 : 10 }, (_, index) => {
      const mask = index + (batch ? 10 : 0)
      return { ...clone(f.packet.candidates[0]), index, scope: { workflow: 'quoting',
        ...Object.fromEntries(keys.filter((_, bit) => mask & (1 << bit)).map(key => [key, context[key]])) } }
    })
    f.accept(packet)
    for (const candidate of packet.candidates) f.store.activate(packet.packet_id, candidate.index, operator)
  }
  assert.equal(f.store.search({ ...query, ...context }).records.length, 10)
  assert.equal(f.store.search({ ...query, ...context, limit: 3 }).records.length, 3)
  assert.equal(f.store.search({ ...query, customer_id: 'different' }).records.length, 1)
})

test('source hash and excerpt are independently checked at stage, review, activation, and search', t => {
  const f = fixture(t)
  const wrongHash = clone(f.packet)
  wrongHash.candidates[0].evidence[0].sha256 = 'a'.repeat(64)
  throwsCode(() => f.store.stage(wrongHash), 'EVIDENCE_CHANGED')
  const wrongExcerpt = clone(f.packet)
  wrongExcerpt.candidates[0].evidence[0].excerpt = 'A nonexistent observation.'
  throwsCode(() => f.store.stage(wrongExcerpt), 'EVIDENCE_EXCERPT_MISSING')
  assert.equal(existsSync(join(f.root, 'events')), false)
  const staged = f.store.stage(f.packet)
  writeFileSync(f.source, 'Changed evidence, with the same cited excerpt: confirm the drawing revision before quoting.\n')
  assert.equal(f.store.review(f.packet.packet_id, f.review(staged)).status, 'REVIEW_FAILED')
  writeFileSync(f.source, f.bytes)
  throwsCode(() => f.store.activate(f.packet.packet_id, 0, operator), 'CANDIDATE_REJECTED')

  const activatedFixture = fixture(t)
  activatedFixture.accept()
  writeFileSync(activatedFixture.source, 'Changed source.')
  throwsCode(() => activatedFixture.store.activate(activatedFixture.packet.packet_id, 0, operator), 'EVIDENCE_CHANGED')
  writeFileSync(activatedFixture.source, activatedFixture.bytes)
  activatedFixture.store.activate(activatedFixture.packet.packet_id, 0, operator)
  writeFileSync(activatedFixture.source, 'Changed after activation.')
  throwsCode(() => activatedFixture.store.search(query), 'EVIDENCE_CHANGED')
  unlinkSync(activatedFixture.source)
  throwsCode(() => activatedFixture.store.search(query), 'EVIDENCE_UNAVAILABLE')
})

test('immutable evidence copies are independently validated and cannot substitute for missing originals', t => {
  const f = fixture(t)
  const staged = f.store.stage(f.packet)
  const copy = join(f.root, 'evidence', `${f.packet.candidates[0].evidence[0].sha256}.bin`)
  replaceImmutable(copy, 'Forged copy.')
  assert.equal(f.store.review(f.packet.packet_id, f.review(staged)).status, 'REVIEW_FAILED')
  throwsCode(() => f.store.stage(f.packet), 'INTEGRITY_ERROR')
  const missing = fixture(t)
  missing.accept()
  unlinkSync(missing.source)
  throwsCode(() => missing.store.activate(missing.packet.packet_id, 0, operator), 'EVIDENCE_UNAVAILABLE')
  const active = fixture(t)
  active.accept()
  active.store.activate(active.packet.packet_id, 0, operator)
  const [record] = active.store.search(query).records
  chmodSync(record.evidence[0].copied_path, 0o600)
  throwsCode(() => active.store.search(query), 'INTEGRITY_ERROR')
  chmodSync(record.evidence[0].copied_path, 0o400)
  replaceImmutable(record.evidence[0].copied_path, 'Forged private evidence.')
  throwsCode(() => active.store.search(query), 'INTEGRITY_ERROR')
})

test('tampering with any packet, review, active, or retirement event fails closed on reads and mutations', t => {
  for (const eventIndex of [0, 1, 2, 3]) {
    const f = fixture(t)
    f.accept()
    const active = f.store.activate(f.packet.packet_id, 0, operator)
    f.store.retire(active.record_id, 'Replaced by revised evidence.')
    const path = eventPaths(f.root)[eventIndex]
    const content = JSON.parse(readFileSync(path, 'utf8'))
    content.data.tampered = true
    replaceImmutable(path, JSON.stringify(content))
    throwsCode(() => f.store.search(query), 'INTEGRITY_ERROR')
    throwsCode(() => f.store.stage(f.packet), 'INTEGRITY_ERROR')
    throwsCode(() => f.store.retire(active.record_id, 'Retire again.'), 'INTEGRITY_ERROR')
  }
  const f = fixture(t)
  f.accept()
  const path = eventPaths(f.root)[0]
  chmodSync(path, 0o600)
  throwsCode(() => f.store.search(query), 'INTEGRITY_ERROR')
})

test('journal gaps, symlinks, hardlinks, and unsafe namespace modes are integrity failures', t => {
  for (const change of [
    f => unlinkSync(eventPaths(f.root)[0]),
    f => { const path = eventPaths(f.root)[0]; unlinkSync(path); symlinkSync(f.source, path) },
    f => linkSync(eventPaths(f.root)[0], join(f.privateDir, 'event-hardlink')),
    f => chmodSync(join(f.root, 'events'), 0o755),
    f => { rmSync(join(f.root, 'evidence'), { recursive: true }); symlinkSync(f.sourceDir, join(f.root, 'evidence')) },
    f => writeFileSync(join(f.root, 'events', 'unexpected.json'), '{}', { mode: 0o400 }),
  ]) {
    const f = fixture(t)
    f.accept()
    change(f)
    throwsCode(() => f.store.search(query), 'INTEGRITY_ERROR')
  }
})

test('root and source paths must be absolute, private, owner-controlled, and free of symlinks', t => {
  const f = fixture(t)
  for (const root of ['relative', `${f.root}/.`, `${f.root}/../knowledge`, `${f.root}/`, '/', `${f.root}\0bad`]) {
    throwsCode(() => new KnowledgeStore(root), 'UNSAFE_PATH')
  }
  throwsCode(() => new KnowledgeStore(checkout), 'CHECKOUT_PATH_DENIED')
  throwsCode(() => new KnowledgeStore(dirname(checkout)), 'CHECKOUT_PATH_DENIED')
  throwsCode(() => new KnowledgeStore(join(f.privateDir, 'absent')), 'PRIVATE_ROOT_REQUIRED')
  chmodSync(f.root, 0o755)
  throwsCode(() => new KnowledgeStore(f.root), 'PRIVATE_DIRECTORY_REQUIRED')
  chmodSync(f.root, 0o700)
  const rootLink = join(f.privateDir, 'root-link')
  symlinkSync(f.root, rootLink)
  throwsCode(() => new KnowledgeStore(rootLink), 'UNSAFE_PATH')
  throwsCode(() => new KnowledgeStore(join(rootLink, 'nested')), 'UNSAFE_PATH')
  chmodSync(f.privateDir, 0o777)
  throwsCode(() => new KnowledgeStore(f.root), 'UNSAFE_PATH')
  chmodSync(f.privateDir, 0o700)
  const link = join(f.sourceDir, 'linked.txt')
  symlinkSync(f.source, link)
  const linkedPacket = clone(f.packet)
  linkedPacket.candidates[0].evidence[0].path = link
  throwsCode(() => f.store.stage(linkedPacket), 'EVIDENCE_UNAVAILABLE')
  const linkedDir = join(f.privateDir, 'linked-sources')
  symlinkSync(f.sourceDir, linkedDir)
  linkedPacket.candidates[0].evidence[0].path = join(linkedDir, 'operator-observation.txt')
  throwsCode(() => f.store.stage(linkedPacket), 'EVIDENCE_UNAVAILABLE')
  chmodSync(f.source, 0o644)
  throwsCode(() => f.store.stage(f.packet), 'EVIDENCE_UNAVAILABLE')
  chmodSync(f.source, 0o600)
  chmodSync(f.sourceDir, 0o755)
  throwsCode(() => f.store.stage(f.packet), 'EVIDENCE_UNAVAILABLE')
  chmodSync(f.sourceDir, 0o700)
  linkSync(f.source, join(f.sourceDir, 'hardlink.txt'))
  throwsCode(() => f.store.stage(f.packet), 'EVIDENCE_UNAVAILABLE')
})

test('roots are pinned across calls and stored evidence cannot be cited as a new operator source', t => {
  const f = fixture(t)
  f.accept()
  const packet = clone(f.packet)
  packet.packet_id = 'self-citation'
  packet.candidates[0].evidence[0].path = join(f.root, 'evidence', `${packet.candidates[0].evidence[0].sha256}.bin`)
  throwsCode(() => f.store.stage(packet), 'STORE_SOURCE_DENIED')
  renameSync(f.root, join(f.privateDir, 'old-root'))
  mkdirSync(f.root, { mode: 0o700 })
  throwsCode(() => f.store.search(query), 'ROOT_CHANGED')
})

test('group/other-writable ancestors are denied for roots and sources, without a sticky-bit exemption', t => {
  const f = fixture(t), ancestor = join(f.privateDir, 'writable-ancestor'), root = join(ancestor, 'private-root')
  mkdirSync(ancestor, { mode: 0o700 })
  mkdirSync(root, { mode: 0o700 })
  const source = join(root, 'operator-observation.txt')
  writeFileSync(source, f.bytes, { mode: 0o600 })
  const packet = clone(f.packet)
  packet.candidates[0].evidence[0].path = source
  for (const mode of [0o720, 0o702, 0o770, 0o707, 0o1720, 0o1702, 0o1777]) {
    chmodSync(ancestor, mode)
    assert.equal(lstatSync(ancestor).mode & 0o7777, mode)
    throwsCode(() => new KnowledgeStore(root), 'UNSAFE_PATH')
    throwsCode(() => f.store.stage(packet), 'EVIDENCE_UNAVAILABLE')
  }
  chmodSync(ancestor, 0o700)
  assert.equal(f.store.stage(packet).status, 'STAGED')
  const sticky = lstatSync(tmpdir())
  assert.equal(sticky.uid, 0)
  assert.ok(sticky.mode & 0o1000)
  assert.ok(sticky.mode & 0o022)
  throwsCode(() => new KnowledgeStore(join(tmpdir(), 'keller-knowledge-denied-root')), 'UNSAFE_PATH')
})

test('unknown fields, unsafe authorities, bad scopes, excessive batches, and malformed dates are rejected', t => {
  const changes = [
    packet => { packet.extra = true },
    packet => { packet.candidates[0].extra = true },
    packet => { delete packet.candidates[0].topic },
    packet => { packet.candidates[0].topic = '' },
    packet => { packet.candidates[0].topic = 'x'.repeat(81) },
    packet => { packet.candidates[0].scope.extra = true },
    packet => { packet.candidates[0].evidence[0].extra = true },
    packet => { delete packet.candidates[0].scope.workflow },
    packet => { packet.candidates[0].scope.workflow = '' },
    packet => { packet.candidates[0].kind = 'agent_narrative' },
    packet => { packet.candidates[0].evidence[0].authority = 'agent_narrative' },
    packet => { packet.candidates[0].statement = 'x'.repeat(301) },
    packet => { packet.candidates[0].evidence[0].excerpt = 'x'.repeat(1025) },
    packet => { packet.candidates[0].evidence = [] },
    packet => { packet.candidates[0].evidence.push(clone(packet.candidates[0].evidence[0])) },
    packet => { packet.candidates[0].kind = 'specification' },
    packet => { packet.candidates[0].index = -1 },
    packet => { packet.candidates.push(clone(packet.candidates[0])) },
    packet => { packet.candidates = Array.from({ length: 11 }, (_, index) => ({ ...clone(packet.candidates[0]), index })) },
    packet => { packet.candidates[0].valid_from = '2026-02-30' },
    packet => { packet.candidates[0].valid_until = '2026-01-01' },
    packet => { packet.candidates[0].evidence[0].path = cli },
    packet => { packet.candidates[0].evidence[0].sha256 = 'not-a-hash' },
  ]
  const f = fixture(t)
  for (const change of changes) {
    const packet = clone(f.packet)
    change(packet)
    assert.throws(() => f.store.stage(packet))
  }
  assert.deepEqual(readdirSync(f.root), [])
  throwsCode(() => new KnowledgeStore(f.root, { unrecognized: true }), 'INVALID_SCHEMA')
  throwsCode(() => new KnowledgeStore(f.root, { readOnly: 'yes' }), 'INVALID_SCHEMA')
})

test('secrets and evaluation material are rejected in snippets, paths, excerpts, and entire source bytes', t => {
  const f = fixture(t)
  for (const statement of ['password=synthetic-secret', 'api_key: synthetic-key', 'Authorization: Bearer synthetic-token',
    'Use the oracle answer.', 'Use the holdout finding.', 'target_unit_price: 42', 'grade: ACCEPT',
    'Agent narrative establishes the rule.', 'Set the labor rate to $50 per hour.', 'price: 20', 'Apply 20% markup.']) {
    const packet = clone(f.packet)
    packet.candidates[0].statement = statement
    assert.throws(() => f.store.stage(packet))
  }
  for (const sourceText of ['password=synthetic-secret', '{"target_unit_price":42}', 'A holdout finding.', 'oracle: hidden answer', '{"grade":"PASS"}']) {
    writeFileSync(f.source, `${f.bytes}${sourceText}`)
    const packet = clone(f.packet)
    packet.candidates[0].evidence[0].sha256 = hash(readFileSync(f.source))
    assert.throws(() => f.store.stage(packet))
  }
  writeFileSync(f.source, f.bytes)
  const excerpt = clone(f.packet)
  excerpt.candidates[0].evidence[0].excerpt = 'oracle answer'
  throwsCode(() => f.store.stage(excerpt), 'PROHIBITED_EVALUATION_MATERIAL')
  for (const filename of ['oracle.json', 'target.json', 'grade.json', 'holdout.txt']) {
    const packet = clone(f.packet)
    packet.candidates[0].evidence[0].path = join(f.sourceDir, filename)
    throwsCode(() => f.store.stage(packet), 'PROHIBITED_EVALUATION_MATERIAL')
  }
  assert.deepEqual(readdirSync(f.root), [])
})

test('reference text is stored as evidence and never executed as instructions', t => {
  const f = fixture(t), marker = join(f.privateDir, 'must-not-exist')
  const bytes = `${f.bytes}Reference text: writeFileSync(${JSON.stringify(marker)}, 'executed')\n`
  writeFileSync(f.source, bytes)
  f.packet.candidates[0].evidence[0].sha256 = hash(bytes)
  f.packet.candidates[0].evidence[0].excerpt = `writeFileSync(${JSON.stringify(marker)}, 'executed')`
  f.accept()
  f.store.activate(f.packet.packet_id, 0, operator)
  assert.equal(f.store.search(query).records[0].evidence[0].excerpt, f.packet.candidates[0].evidence[0].excerpt)
  assert.equal(existsSync(marker), false)
})

test('duplicate activation records a disposition, and scope conflicts require explicit retirement', t => {
  const f = fixture(t)
  f.accept()
  const first = f.store.activate(f.packet.packet_id, 0, operator)
  const duplicate = clone(f.packet)
  duplicate.packet_id = 'duplicate'
  duplicate.candidates[0].topic = 'same-statement-alternative-topic'
  f.accept(duplicate)
  const disposed = f.store.activate(duplicate.packet_id, 0, operator)
  assert.equal(disposed.status, 'DUPLICATE_REJECTED')
  assert.equal(disposed.disposition, 'KEEP_EXISTING_REJECT_REDUNDANT')
  assert.equal(disposed.record_id, first.record_id)
  assert.match(disposed.disposition_sha256, /^[a-f0-9]{64}$/)
  assert.equal(f.store.search(query).records.length, 1)
  throwsCode(() => f.store.activate(duplicate.packet_id, 0, operator), 'CANDIDATE_ALREADY_DISPOSED')
  const conflict = clone(f.packet)
  conflict.packet_id = 'replacement'
  conflict.candidates[0].statement = 'Confirm the specified finish before quoting.'
  f.accept(conflict)
  const before = eventPaths(f.root)
  throwsCode(() => f.store.activate(conflict.packet_id, 0, operator), 'ACTIVE_SCOPE_CONFLICT')
  assert.deepEqual(eventPaths(f.root), before)
  assert.equal(f.store.search(query).records[0].statement, f.packet.candidates[0].statement)
  const retired = f.store.retire(first.record_id, 'The operator selected the independently reviewed replacement.')
  assert.equal(retired.status, 'RETIRED')
  assert.equal(retired.record_sha256, first.record_sha256)
  assert.deepEqual(f.store.search(query).records, [])
  throwsCode(() => f.store.retire(first.record_id, 'Repeated retirement.'), 'RECORD_ALREADY_RETIRED')
  const replacement = f.store.activate(conflict.packet_id, 0, operator)
  assert.notEqual(replacement.record_id, first.record_id)
  assert.equal(new KnowledgeStore(f.root).search(query).records[0].statement, conflict.candidates[0].statement)
})

test('different topics coexist for complementary procedures and specifications at the same exact scope', t => {
  const f = fixture(t)
  const scope = { workflow: 'quoting', customer_id: 'CUSTOMER-A', part_no: 'PART-A', revision: 'R1' }
  const candidates = [
    { kind: 'procedure', topic: 'drawing-revision', statement: 'Confirm the drawing revision before quoting.', scope: { workflow: 'quoting' } },
    { kind: 'procedure', topic: 'finish-check', statement: 'Confirm the specified finish before quoting.', scope: { workflow: 'quoting' } },
    { kind: 'specification', topic: 'finish', statement: 'The specified finish is satin.', scope },
    { kind: 'specification', topic: 'drawing-revision', statement: 'The specified drawing revision is R1.', scope },
  ].map((candidate, index) => ({ ...clone(f.packet.candidates[0]), ...candidate, index }))
  const bytes = `${f.bytes}The specified drawing revision is R1.\n`
  writeFileSync(f.source, bytes)
  for (const candidate of candidates) candidate.evidence[0].sha256 = hash(bytes)
  f.packet.candidates = candidates
  f.accept()
  for (const candidate of candidates) f.store.activate(f.packet.packet_id, candidate.index, operator)
  assert.deepEqual(f.store.search(query).records.map(record => record.topic).sort(), ['drawing-revision', 'finish-check'])
  const full = f.store.search({ ...query, ...scope })
  assert.equal(full.records.length, 4)
  assert.deepEqual(full.records.filter(record => record.kind === 'specification').map(record => record.topic).sort(), ['drawing-revision', 'finish'])
  const replacement = { ...clone(f.packet), packet_id: 'finish-replacement', candidates: [{ ...clone(candidates[2]), statement: 'The specified finish is brushed satin.' }] }
  f.accept(replacement)
  throwsCode(() => f.store.activate(replacement.packet_id, 2, operator), 'ACTIVE_SCOPE_CONFLICT')
  const oldFinish = full.records.find(record => record.kind === 'specification' && record.topic === 'finish')
  f.store.retire(oldFinish.record_id, 'Replace this specification topic; retain the other complementary guidance.')
  f.store.activate(replacement.packet_id, 2, operator)
  assert.equal(f.store.search({ ...query, ...scope }).records.length, 4)
})

test('exact specifications outrank broad procedures before limiting, without inferring missing revision', t => {
  const f = fixture(t)
  const scope = { workflow: 'quoting', customer_id: 'C', part_no: 'P', revision: 'R1' }
  const statements = Array.from({ length: 10 }, (_, index) => `Verify drawing requirement ${index} before quoting.`)
  const bytes = `${f.bytes}${statements.join('\n')}\n`
  writeFileSync(f.source, bytes)
  const packet = clone(f.packet)
  packet.candidates = statements.map((statement, index) => ({ ...clone(packet.candidates[0]), index, topic: `requirement-${index}`,
    statement, valid_from: index === 1 ? '2026-10-03' : '2026-10-02',
    evidence: [{ ...clone(packet.candidates[0].evidence[0]), sha256: hash(bytes), excerpt: statement }],
  }))
  f.accept(packet)
  const broad = packet.candidates.map(candidate => f.store.activate(packet.packet_id, candidate.index, operator))
  const exact = { ...clone(f.packet), packet_id: 'exact-specification', candidates: [{ ...clone(f.packet.candidates[0]),
    kind: 'specification', topic: 'finish', statement: 'The specified finish is satin.', scope,
    evidence: [{ ...clone(f.packet.candidates[0].evidence[0]), sha256: hash(bytes), excerpt: 'The specified finish is satin.' }],
  }] }
  f.accept(exact)
  const specification = f.store.activate(exact.packet_id, 0, operator)
  assert.equal(f.store.search({ ...query, ...scope, limit: 1 }).records[0].record_id, specification.record_id)
  const incomplete = { ...query, customer_id: 'C', part_no: 'P', limit: 1 }
  assert.equal(f.store.search(incomplete).records[0].record_id, broad[1].record_id)
  const expected = broad.map((record, index) => ({ record, date: packet.candidates[index].valid_from }))
    .sort((a, b) => b.date.localeCompare(a.date) || a.record.record_id.localeCompare(b.record.record_id))
    .map(item => item.record.record_id)
  assert.deepEqual(f.store.search(query).records.map(record => record.record_id), expected)
})

test('operator attestation schema is strict, named, and requires both well-formed report hashes', t => {
  const f = fixture(t)
  f.accept()
  for (const invalid of [{ ...operator, operator: '' }, { ...operator, reason: '' }, { ...operator, extra: true },
    { ...operator, development_report_sha256: 'invalid' }, { ...operator, confirmation_report_sha256: null }]) {
    assert.throws(() => f.store.activate(f.packet.packet_id, 0, invalid))
  }
  assert.deepEqual(f.store.search(query).records, [])
  const active = f.store.activate(f.packet.packet_id, 0, { ...operator, operator: 'Locally asserted name' })
  assert.equal(active.operator_attestation.operator, 'Locally asserted name')
  throwsCode(() => f.store.retire(active.record_id, ''), 'INVALID_TEXT')
  throwsCode(() => f.store.retire('not-an-id', 'Reason.'), 'INVALID_HASH')
})

test('read-only construction and search never create files and all mutations are denied', t => {
  const f = fixture(t), store = new KnowledgeStore(f.root, { readOnly: true })
  const before = lstatSync(f.root)
  assert.deepEqual(store.search(query).records, [])
  assert.deepEqual(readdirSync(f.root), [])
  assert.equal(lstatSync(f.root).mtimeMs, before.mtimeMs)
  throwsCode(() => store.stage(f.packet), 'READ_ONLY')
  throwsCode(() => store.review(f.packet.packet_id, null), 'READ_ONLY')
  throwsCode(() => store.activate(f.packet.packet_id, 0, operator), 'READ_ONLY')
  throwsCode(() => store.retire('a'.repeat(64), 'Reason.'), 'READ_ONLY')
  assert.deepEqual(readdirSync(f.root), [])
  const result = run('search', f.root, query)
  assert.equal(result.status, 0)
  assert.deepEqual(result.output.result.records, [])
  assert.deepEqual(readdirSync(f.root), [])
})

test('a preexisting single-writer lock is never stolen or automatically recovered', t => {
  const f = fixture(t), lock = join(f.root, '.writer.lock')
  const bytes = '{"pid":0,"token":"operator-recovery-required"}'
  writeFileSync(lock, bytes, { mode: 0o600 })
  throwsCode(() => f.store.stage(f.packet), 'STORE_BUSY')
  throwsCode(() => f.store.search(query), 'STORE_BUSY')
  assert.equal(readFileSync(lock, 'utf8'), bytes)
  assert.deepEqual(readdirSync(f.root), ['.writer.lock'])
  unlinkSync(lock)
  symlinkSync(f.source, lock)
  throwsCode(() => f.store.stage(f.packet), 'STORE_BUSY')
  assert.equal(readFileSync(f.source, 'utf8'), f.bytes)
})

async function concurrent(t, root, method, args) {
  const workers = args.map(() => {
    const script = `import { KnowledgeStore } from ${JSON.stringify(pathToFileURL(cli).href)};
      const store = new KnowledgeStore(${JSON.stringify(root)});
      process.once('message', args => {
        try { process.send({ ok: true, result: store[${JSON.stringify(method)}](...args) }); }
        catch (error) { process.send({ ok: false, code: error.code }); }
        process.disconnect();
      });
      process.send({ ready: true });`
    const child = spawn(process.execPath, ['--input-type=module', '-e', script], { stdio: ['ignore', 'ignore', 'pipe', 'ipc'] })
    t.after(() => { if (child.exitCode === null) child.kill() })
    let errors = ''
    child.stderr.on('data', chunk => { errors += chunk })
    const ready = new Promise((resolve, reject) => {
      child.once('message', message => message.ready ? resolve() : reject(new Error('Worker not ready')))
      child.once('error', reject)
    })
    const result = new Promise((resolve, reject) => {
      child.on('message', message => { if (!message.ready) resolve(message) })
      child.once('error', reject)
    })
    const exit = new Promise((resolve, reject) => child.once('close', code => {
      if (code || errors) reject(new Error(`Worker exit ${code}: ${errors}`))
      else resolve()
    }))
    return { child, ready, result, exit }
  })
  await Promise.all(workers.map(worker => worker.ready))
  workers.forEach((worker, index) => worker.child.send(args[index]))
  const results = await Promise.all(workers.map(worker => worker.result))
  await Promise.all(workers.map(worker => worker.exit))
  return results
}

test('concurrent processes serialize immutable stages and allow only one complete review', { timeout: 15000 }, async t => {
  const f = fixture(t)
  const packets = Array.from({ length: 4 }, (_, index) => ({ ...clone(f.packet), packet_id: `concurrent-${index}` }))
  const staged = await concurrent(t, f.root, 'stage', packets.map(packet => [packet]))
  for (const result of staged) assert.ok(result.ok || result.code === 'STORE_BUSY')
  for (const packet of packets) f.store.stage(packet)
  assert.equal(eventPaths(f.root).length, packets.length)
  const frozen = f.store.stage(packets[0])
  const reviews = [f.review(frozen), { ...f.review(frozen), reviewer_id: 'reviewer-2' }]
  const reviewed = await concurrent(t, f.root, 'review', reviews.map(review => [packets[0].packet_id, review]))
  assert.equal(reviewed.filter(result => result.ok).length, 1)
  assert.ok(reviewed.some(result => ['STORE_BUSY', 'REVIEW_ALREADY_RECORDED'].includes(result.code)))
  throwsCode(() => f.store.review(packets[0].packet_id, f.review(frozen)), 'REVIEW_ALREADY_RECORDED')
  f.store.activate(packets[0].packet_id, 0, operator)
  assert.equal(f.store.search(query).records.length, 1)
  assert.equal(existsSync(join(f.root, '.writer.lock')), false)
})

test('CLI implements all five JSON actions with private, hash-bound lifecycle results', t => {
  const f = fixture(t)
  const staged = run('stage', f.root, f.packet)
  assert.equal(staged.status, 0)
  const reviewed = run('review', f.root, { packet_id: f.packet.packet_id, review: f.review(staged.output.result) })
  assert.equal(reviewed.status, 0)
  assert.deepEqual(run('search', f.root, query).output.result.records, [])
  const activated = run('activate', f.root, { packet_id: f.packet.packet_id, candidate_index: 0, operator_attestation: operator })
  assert.equal(activated.status, 0)
  const searched = run('search', f.root, query)
  assert.equal(searched.output.result.records[0].record_id, activated.output.result.record_id)
  assert.equal(searched.output.result.records[0].review_sha256, reviewed.output.result.review_sha256)
  const retired = run('retire', f.root, { record_id: activated.output.result.record_id, reason: 'Explicit operator retirement.' })
  assert.equal(retired.status, 0)
  assert.deepEqual(run('search', f.root, query).output.result.records, [])
})

test('CLI bounds input, rejects invalid JSON and unknown keys, and never echoes private errors', t => {
  const f = fixture(t)
  for (const [action, input, args, code] of [
    ['search', '{', [], 'INVALID_JSON'],
    ['search', '{"workflow":"quoting","workflow":"quoting","as_of":"2026-10-04"}', [], 'INVALID_JSON'],
    ['search', '{"workflow":"quoting","work\\u0066low":"quoting","as_of":"2026-10-04"}', [], 'INVALID_JSON'],
    ['search', Buffer.from([0xc3, 0x28]), [], 'INVALID_JSON'],
    ['search', JSON.stringify({ ...query, unknown: true }), [], 'INVALID_SCHEMA'],
    ['stage', JSON.stringify({ ...f.packet, unknown: true }), [], 'INVALID_SCHEMA'],
    ['search', JSON.stringify(query), ['--extra', 'value'], 'INVALID_ARGUMENTS'],
    ['search', 'x'.repeat(256 * 1024 + 1), [], 'INPUT_TOO_LARGE'],
  ]) {
    const result = run(action, f.root, input, args)
    assert.equal(result.status, 1)
    assert.equal(result.output.ok, false)
    assert.equal(result.output.error.code, code)
    assert.ok(!result.stdout.includes(f.root))
    assert.ok(!result.stdout.includes(f.source))
  }
  const unavailable = run('stage', f.root, { ...f.packet, candidates: [{ ...f.packet.candidates[0], evidence: [{
    ...f.packet.candidates[0].evidence[0], path: join(f.sourceDir, 'absent-private-evidence.txt'),
  }] }] })
  assert.equal(unavailable.status, 1)
  assert.equal(unavailable.output.error.code, 'EVIDENCE_UNAVAILABLE')
  assert.deepEqual(readdirSync(f.root), [])
  const staged = run('stage', f.root, f.packet).output.result
  const failed = run('review', f.root, { packet_id: f.packet.packet_id, review: null })
  assert.equal(failed.status, 0)
  assert.equal(failed.output.result.status, 'REVIEW_FAILED')
  const retried = run('review', f.root, { packet_id: f.packet.packet_id, review: f.review(staged) })
  assert.equal(retried.status, 1)
  assert.equal(retried.output.error.code, 'REVIEW_ALREADY_RECORDED')
})
