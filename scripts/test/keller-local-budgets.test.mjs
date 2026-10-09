import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const script = new URL('../keller-local.mjs', import.meta.url).pathname;

function setup(t) {
  const root = mkdtempSync(join(tmpdir(), 'keller-budget-synthetic-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const register = join(root, 'register.csv');
  const workspace = join(root, 'queue');
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  mkdirSync(join(workspace, 'inbox'), { recursive: true });
  for (const [name, quantity] of [['a.json', 10], ['b.json', 20]]) {
    writeFileSync(join(workspace, 'inbox', name), JSON.stringify({ parts: [{ part_no: 'ABC', quantity }] }));
  }
  const run = extra => spawnSync(process.execPath, [script, 'cycle', '--workspace', workspace,
    '--register', register, ...extra], { encoding: 'utf8', timeout: 20000 });
  return { workspace, run };
}

test('cycle bounds new estimation work without starving jobs behind verified duplicates', t => {
  const { run } = setup(t);
  const first = run(['--max-jobs', '1']);
  assert.equal(first.status, 0, first.stderr);
  assert.deepEqual(JSON.parse(first.stdout).drafted, ['a.json']);
  assert.deepEqual(JSON.parse(first.stdout).deferred, ['b.json']);
  const second = run(['--max-jobs', '1']);
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(JSON.parse(second.stdout).duplicate, ['a.json']);
  assert.deepEqual(JSON.parse(second.stdout).drafted, ['b.json']);
  assert.deepEqual(JSON.parse(second.stdout).deferred, []);
});

test('a timed-out estimator never writes a successful receipt or a fabricated hold price', t => {
  const { run, workspace } = setup(t);
  const result = run(['--timeout-ms', '1', '--max-jobs', '1']);
  assert.notEqual(result.status, 0);
  const cycle = JSON.parse(result.stdout);
  assert.equal(cycle.failed.length, 1);
  assert.deepEqual(cycle.drafted, []);
  assert.deepEqual(cycle.deferred, ['b.json']);
  assert.deepEqual(readdirSync(join(workspace, 'receipts')), []);
  assert.deepEqual(readdirSync(join(workspace, 'held')), []);
});

test('job and time budgets reject coercion, out-of-range values and duplicate options', t => {
  const { run } = setup(t);
  for (const extra of [
    ['--max-jobs', '0'], ['--max-jobs', '101'], ['--max-jobs', '1e1'],
    ['--timeout-ms', 'NaN'], ['--budget-ms', '900001'],
    ['--max-jobs', '1', '--max-jobs', '2'],
  ]) assert.notEqual(run(extra).status, 0);
});
