import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'

const root = resolve(import.meta.dirname, '../..')
const cli = join(root, 'scripts/prepare-worker-rubric.py')
const keys = ['version', 'population', 'validation_weight', 'judge_weight', 'acceptance', 'validation', 'judge']
const sha256 = data => createHash('sha256').update(data).digest('hex')
const rubric = () => ({ version: 1, population: 'synthetic', validation_weight: 0.5, judge_weight: 0.5,
  acceptance: { all_required: true, threshold: 'synthetic threshold' },
  validation: Array.from({ length: 5 }, (_, i) => ({ id: `V${i + 1}`, criterion: `Exact synthetic rule ${i + 1}`, note: { retained: i } })),
  judge: Array.from({ length: 5 }, (_, i) => ({ id: `J${i + 1}`, criterion: `Judge synthetic rule ${i + 1}` })),
  limitations: 'OPERATOR_ONLY prior synthetic score 3/5', history: { outcomes: ['OPERATOR_ONLY'] } })

function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'rubric-projection-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const privateDir = join(dir, 'private')
  mkdirSync(privateDir, { mode: 0o700 })
  const source = join(privateDir, 'criteria.json'), out = join(privateDir, 'worker.json')
  const run = (sourcePath = source, outPath = out) => spawnSync('python3', [cli, '--source', sourcePath, '--out', outPath],
    { encoding: 'utf8', cwd: root })
  return { dir, privateDir, source, out, run }
}

test('projection strips operator outcomes but preserves every normative value unchanged', t => {
  const f = fixture(t), original = rubric(), raw = JSON.stringify(original)
  writeFileSync(f.source, raw, { mode: 0o600 })
  const result = f.run()
  assert.equal(result.status, 0, result.stderr)
  const outputBytes = readFileSync(f.out), projected = JSON.parse(outputBytes)
  assert.deepEqual(Object.keys(projected), keys)
  assert.deepEqual(projected, Object.fromEntries(keys.map(key => [key, original[key]])))
  assert.doesNotMatch(outputBytes.toString(), /OPERATOR_ONLY|3\/5/)
  assert.equal(lstatSync(f.out).mode & 0o777, 0o600)
  assert.equal(readFileSync(f.source, 'utf8'), raw)
  assert.deepEqual(JSON.parse(result.stdout), { source_sha256: sha256(raw), worker_view_sha256: sha256(outputBytes),
    normative_equal: true, normative_keys: keys })
})

test('incomplete, duplicate or invalid criterion arrays and duplicate JSON keys fail closed', t => {
  const f = fixture(t)
  const bad = [
    data => { data.validation.pop() },
    data => { data.validation[2].id = 'V1' },
    data => { data.validation[2].id = 'V6' },
    data => { data.judge[4].id = 'J1' },
    data => { data.judge[0].criterion = '' },
    data => { data.judge[0].criterion = ['not prose'] },
    data => { delete data.acceptance },
  ]
  for (const mutate of bad) {
    const data = rubric()
    mutate(data)
    writeFileSync(f.source, JSON.stringify(data))
    const result = f.run()
    assert.equal(result.status, 2)
    assert.equal(result.stdout, '')
    assert.doesNotMatch(result.stderr, /OPERATOR_ONLY|3\/5/)
    assert.throws(() => readFileSync(f.out))
  }
  for (const text of [JSON.stringify(rubric()).replace('"version":1', '"version":1,"version":2'),
    JSON.stringify(rubric()).replace('"id":"J1"', '"id":"J1","id":"J2"'), '{not json}']) {
    writeFileSync(f.source, text)
    assert.equal(f.run().status, 2)
    assert.throws(() => readFileSync(f.out))
  }
})

test('non-overwrite output rejects aliases, symlinks, unsafe parents and repository paths', t => {
  const f = fixture(t)
  writeFileSync(f.source, JSON.stringify(rubric()))
  for (const dest of [f.source, join(root, 'scripts/test/worker-context.test.mjs')]) {
    const before = readFileSync(dest)
    assert.equal(f.run(f.source, dest).status, 2)
    assert.deepEqual(readFileSync(dest), before)
  }
  writeFileSync(f.out, 'existing')
  assert.equal(f.run().status, 2)
  assert.equal(readFileSync(f.out, 'utf8'), 'existing')
  rmSync(f.out)
  symlinkSync(f.source, f.out)
  assert.equal(f.run().status, 2)
  assert.equal(readFileSync(f.source, 'utf8'), JSON.stringify(rubric()))
  rmSync(f.out)
  const link = join(f.dir, 'link')
  symlinkSync(f.privateDir, link)
  assert.equal(f.run(f.source, join(link, 'worker.json')).status, 2)
  chmodSync(f.privateDir, 0o755)
  assert.equal(f.run().status, 2)
  chmodSync(f.privateDir, 0o700)
  assert.equal(f.run(f.source, `${f.privateDir}/../private/worker.json`).status, 2)
  assert.throws(() => readFileSync(f.out))
})
