import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { test } from 'node:test'
import { beforeScopedCall, loadEvaluationScope } from '../mcp-evaluation-scope.mjs'

const root = resolve(import.meta.dirname, '../..')
const contract = join(root, 'docs/pricing-evals-and-orders.md')
const operatorGuide = join(root, 'docs/pricing-evaluation-operator-guide.md')
const exposed = [
  ...['keller-data-analysis', 'keller-estimator-evals', 'keller-quote-estimator', 'keller-quote-register', 'polygres']
    .map(name => join(root, `.agents/skills/${name}/SKILL.md`)),
  contract, join(root, 'estimator/src/order.ts'), join(root, 'estimator/src/types.ts'),
]

const archivedResult = 'The final matched 50-case document-price experiment (2026-09-28) priced 48/50 in both register conditions. Against the **same PDF targets**, the internal register had median APE 75.5361%, within ±20% on 18.75% of priced cases, all-pass 9/50; the verified register had median APE 63.3716%, within ±20% on 16.6667% of priced cases, all-pass 8/50. The verified run exposed 234/234 analog refs with verified basis and held two no-analog lines; neither run exposed source/cutoff leaks. The lower median came with **worse** within-20 and all-pass, so it is not a blanket accuracy gain or an autonomous pricing release. The source+lock SHA-256 was `e52bfce6b646af8ac0066a8d1552fb71a27e44eb717b186ac59cb710638c92e4` and the selected document case IDs SHA-256 was `bd1b94393891fca2328e80aaaeb1f325381231c99f3c0c2ff006203027e2c4d2`. This was an offline harness run directed by Codex GPT-6 Sol (medium), **not** model-generated pricing. A retrospective future-visible score would answer a different question. The separate fixed legacy 250-case eval has internal targets and cannot be numerically compared with this PDF-target experiment.'
const archivedQualitativeResult = 'The [exact-part and quantity-weighting experiment](pricing-optimization.md) reports aggregate gains alongside a diagnostic holdout within-20% regression and supplemental signed-dollar underquoting. Those observed historical results predate the combined admission pipeline and are not evidence that the combined policy improves pricing accuracy; do not tune against them as fresh blind targets.'

test('all eight actual worker-readable contracts exclude archived numeric and qualitative outcomes', () => {
  assert.equal(exposed.length, 8)
  for (const path of exposed) {
    const text = readFileSync(path, 'utf8')
    assert.doesNotMatch(text, /75\.5361%|63\.3716%|18\.75% of priced cases|16\.6667% of priced cases|all-pass [89]\/50|priced 48\/50|234\/234 analog refs/i, path)
    assert.doesNotMatch(text, /exact-part and quantity-weighting experiment[^\n]*(aggregate gains|holdout|underquoting)|aggregate gains alongside a diagnostic holdout|supplemental signed-dollar underquoting/i, path)
    assert.ok(!text.includes(archivedResult), path)
    assert.ok(!text.includes(archivedQualitativeResult), path)
  }
  const workerContract = readFileSync(contract, 'utf8')
  for (const invariant of ['customer_quote_pdf', 'verified letter date', 'five decimals', 'source `quote_no`',
    'Cost-plus sell unit', 'rounds half-up', 'PRICED_REQUIRES_REVIEW', 'named human']) {
    assert.ok(workerContract.includes(invariant), `missing worker contract invariant: ${invariant}`)
  }
})

test('production memory expands one isolated hop without expanding orientation or operator diagnostics', () => {
  const profile = readFileSync(join(root, 'profiles/Keller Codex.yaml'), 'utf8')
  assert.match(profile, /inject:\n  - "\[\[keller-orientation\]\]"/)
  assert.match(profile, /  - "\[\[keller-production-quote-memory\]\]"/)
  const orientation = readFileSync(join(root, 'inject/keller-orientation.md'), 'utf8')
  assert.doesNotMatch(orientation.split('---')[1], /^depth: [1-9]/m)
  const seed = readFileSync(join(root, 'inject/keller-production-quote-memory.md'), 'utf8')
  const [, frontmatter, body] = seed.split('---')
  assert.match(frontmatter, /^depth: 1$/m)
  assert.match(frontmatter, /^edge-kinds: \[navigational\]$/m)
  const targets = [...body.matchAll(/\[\[([^\]]+)\]\]/g)].map(match => match[1]).sort()
  const memory = 'Production RFQ retention and reviewed should-cost routing'
  assert.deepEqual(targets, [memory])
  const paths = ['inject/keller-orientation.md', 'inject/keller-production-quote-memory.md',
    `knowledge/claims/${memory}.md`, 'skills/keller-quote-estimator.md']
  for (const path of paths) {
    const text = readFileSync(join(root, path), 'utf8')
    assert.ok(!text.includes(archivedResult), path)
    assert.ok(!text.includes(archivedQualitativeResult), path)
    assert.doesNotMatch(text, /75\.5361%|63\.3716%|all-pass [89]\/50|priced 48\/50|234\/234 analog refs/i, path)
    assert.doesNotMatch(text, /\[\[[^\]]*(operator findings|diagnostic|evaluation results)[^\]]*\]\]/i, path)
  }
  const memoryBody = readFileSync(join(root, `knowledge/claims/${memory}.md`), 'utf8')
  for (const invariant of ['intake.ts', 'costing.ts', 'quote/tool.ts', 'customer_release_authorized',
    'Cognition memory-repo reference', 'not real-job quote quality']) assert.ok(memoryBody.includes(invariant), invariant)
  assert.match(readFileSync(join(root, 'skills/keller-quote-estimator.md'), 'utf8'), /\.agents\/skills\/keller-quote-estimator\/SKILL\.md/)
})

test('operator-only guide preserves original result text and its denominators and caveats', () => {
  const guide = readFileSync(operatorGuide, 'utf8')
  assert.ok(guide.includes(archivedResult))
  assert.ok(guide.includes(archivedQualitativeResult))
  for (const fragment of ['48/50 in both register conditions', '18.75% of priced cases', '16.6667% of priced cases',
    'all-pass 9/50', 'all-pass 8/50', 'held two no-analog lines', 'neither run exposed source/cutoff leaks',
    'not a blanket accuracy gain or an autonomous pricing release', '**not** model-generated pricing',
    'cannot be numerically compared with this PDF-target experiment']) {
    assert.ok(guide.includes(fragment), `missing archived caveat: ${fragment}`)
  }
})

test('actual scoped guard allows the contract and denies the operator guide before a read', t => {
  const dir = mkdtempSync(join(tmpdir(), 'worker-context-'))
  t.after(() => rmSync(dir, { recursive: true, force: true }))
  const privateDir = join(dir, 'private')
  mkdirSync(privateDir, { mode: 0o700 })
  const scopePath = join(privateDir, 'scope.json')
  const scope = {
    schema_version: 1, case_id: 'synthetic-case', corpus: 'a'.repeat(64), quote_date: '2025-01-01',
    excluded_quote_nos: ['TARGET'], eligible_prices: [], allowed_files: [contract],
    request: { order_id: 'ORDER', quote_date: '2025-01-01', customer: 'Synthetic', customer_id: 'C',
      reviewer: 'Casey', parts: [{ line_id: 'L1', part_no: 'P', quantity: 3 }], charges: { shipping: 0, tax: 0 } },
  }
  writeFileSync(scopePath, JSON.stringify(scope), { mode: 0o600 })
  const guard = loadEvaluationScope(scopePath, root)
  assert.doesNotThrow(() => beforeScopedCall('read_file_pinned', { file_path: contract }, guard))
  assert.throws(() => beforeScopedCall('read_file_pinned', { file_path: operatorGuide }, guard), /File unavailable in evaluation scope/)
  assert.throws(() => beforeScopedCall('read_file_pinned', {
    file_path: join(root, 'docs/steve-development-diagnostic.md'),
  }, guard), /File unavailable in evaluation scope/)
  writeFileSync(scopePath, JSON.stringify({ ...scope, allowed_files: [contract, operatorGuide] }))
  assert.throws(() => loadEvaluationScope(scopePath, root), /Invalid allowed public file/)
})
