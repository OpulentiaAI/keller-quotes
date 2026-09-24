import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { hostname } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const job = join(repo, 'scripts/keller-local.mjs');

test('onboard, draft, retry after a missing receipt, deduplicate, and hold bad input', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-local-test-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const register = join(scratch, 'quotes.csv');
  const fixture = join(scratch, 'request.json');
  const workspace = join(scratch, 'queue');
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  writeFileSync(fixture, JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] }));
  const run = (mode) => {
    const env = { ...process.env };
    delete env.POLYGRES_DIRECT_URL;
    delete env.AI_GATEWAY_API_KEY;
    const result = spawnSync(process.execPath, [job, mode, '--workspace', workspace,
      '--register', register, '--fixture', fixture], { cwd: repo, env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  };
  const onboard = run('onboard');
  assert.equal(onboard.local, 'LOCAL_READY');
  assert.equal(onboard.external, 'INTEGRATION_BLOCKED');
  assert.equal(onboard.runtime_persistence, 'UNVERIFIED');
  assert.equal(onboard.scheduler_workspace_binding, 'UNVERIFIED');
  assert.equal(onboard.fixture_lines, 1);

  const input = readFileSync(fixture);
  const inputHash = createHash('sha256').update(input).digest('hex');
  const registerHash = createHash('sha256').update(readFileSync(register)).digest('hex');
  const hash = createHash('sha256').update(`keller-job-v1\n${inputHash}\n${registerHash}`).digest('hex');
  writeFileSync(join(workspace, 'inbox', 'rfq.json'), input);
  assert.deepEqual(run('cycle').drafted, ['rfq.json']);
  const draft = join(workspace, 'drafts', `${hash}.json`);
  const receipt = join(workspace, 'receipts', `${hash}.json`);
  const proof = join(workspace, 'proofs', `${hash}.json`);
  assert.equal(JSON.parse(readFileSync(draft, 'utf8')).lines[0].unit_price, 10);
  assert.equal(JSON.parse(readFileSync(receipt, 'utf8')).state, 'DRAFT_REQUIRES_MANUAL_REVIEW');
  assert.equal(JSON.parse(readFileSync(receipt, 'utf8')).register_sha256, registerHash);
  assert.equal(JSON.parse(readFileSync(proof, 'utf8')).draft_sha256,
    createHash('sha256').update(readFileSync(draft)).digest('hex'));
  const original = readFileSync(draft, 'utf8');
  assert.deepEqual(run('cycle').duplicate, ['rfq.json']);

  unlinkSync(receipt);
  assert.deepEqual(run('cycle').drafted, ['rfq.json']);
  assert.equal(readFileSync(draft, 'utf8'), original);
  assert.equal(existsSync(receipt), true);

  writeFileSync(join(workspace, 'inbox', 'duplicate.json'), input);
  assert.deepEqual(run('cycle').duplicate, ['duplicate.json', 'rfq.json']);
  assert.equal(readdirSync(join(workspace, 'drafts')).length, 1);

  writeFileSync(join(workspace, 'inbox', 'bad.json'), '{');
  assert.deepEqual(run('cycle').held, ['bad.json']);
  assert.deepEqual(run('cycle').held, ['bad.json']);
  writeFileSync(join(workspace, 'inbox', 'bad.json'), JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 20 }] }));
  assert.deepEqual(run('cycle').drafted, ['bad.json']);
  assert.equal(readdirSync(join(workspace, 'drafts')).length, 2);

  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,12\n');
  assert.deepEqual(run('cycle').drafted, ['bad.json', 'duplicate.json']);
  assert.equal(readFileSync(draft, 'utf8'), original);
  assert.equal(readdirSync(join(workspace, 'drafts')).length, 4);
});

test('corrupted receipts and orphan drafts are held for explicit reconciliation', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-corrupt-test-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const workspace = join(scratch, 'queue');
  const register = join(scratch, 'quotes.csv');
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  const invoke = () => {
    const result = spawnSync(process.execPath, [job, 'cycle', '--workspace', workspace,
      '--register', register], { cwd: repo, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  };
  const input = JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] });
  const fixture = join(scratch, 'fixture.json');
  writeFileSync(fixture, input);
  const setup = spawnSync(process.execPath, [job, 'onboard', '--workspace', workspace, '--register', register,
    '--fixture', fixture], { cwd: repo, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  writeFileSync(join(workspace, 'inbox', 'a.json'), input);
  assert.deepEqual(invoke().drafted, ['a.json']);
  const [key] = readdirSync(join(workspace, 'drafts')).map((name) => name.replace(/\.json$/, ''));
  const draft = join(workspace, 'drafts', `${key}.json`);
  const receipt = join(workspace, 'receipts', `${key}.json`);
  writeFileSync(draft, readFileSync(draft, 'utf8').replace('"unit_price": 10', '"unit_price": 999'));
  assert.deepEqual(invoke().held, ['a.json']);
  assert.equal(JSON.parse(readFileSync(join(workspace, 'held', `${key}.json`), 'utf8')).state,
    'HELD_AMBIGUOUS_ARTIFACT');
  assert.equal(existsSync(receipt), true);

  const changed = JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 20 }] });
  writeFileSync(join(workspace, 'inbox', 'b.json'), changed);
  assert.deepEqual(invoke().drafted, ['b.json']);
  const other = readdirSync(join(workspace, 'drafts')).map((name) => name.replace(/\.json$/, '')).find((name) => name !== key);
  const orphan = join(workspace, 'drafts', `${other}.json`);
  unlinkSync(join(workspace, 'proofs', `${other}.json`));
  unlinkSync(join(workspace, 'receipts', `${other}.json`));
  assert.deepEqual(invoke().held, ['a.json', 'b.json']);
  assert.equal(existsSync(orphan), true);
  assert.equal(existsSync(join(workspace, 'receipts', `${other}.json`)), false);
});

test('concurrent cycles claim one input before writing a draft', async (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-concurrent-test-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const workspace = join(scratch, 'queue');
  const register = join(scratch, 'quotes.csv');
  const fixture = join(scratch, 'fixture.json');
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  writeFileSync(fixture, JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] }));
  const setup = spawnSync(process.execPath, [job, 'onboard', '--workspace', workspace,
    '--register', register, '--fixture', fixture],
    { cwd: repo, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  writeFileSync(join(workspace, 'inbox', 'a.json'), JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] }));
  const run = () => new Promise((done) => {
    const child = spawn(process.execPath, [job, 'cycle', '--workspace', workspace, '--register', register], { cwd: repo });
    let stdout = ''; let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (code) => done({ code, stdout, stderr }));
  });
  const results = await Promise.all([run(), run()]);
  for (const result of results) assert.equal(result.code, 0, result.stderr);
  const cycles = results.map((result) => JSON.parse(result.stdout));
  assert.equal(cycles.reduce((sum, cycle) => sum + cycle.drafted.length, 0), 1);
  assert.equal(cycles.reduce((sum, cycle) => sum + cycle.claimed.length + cycle.duplicate.length, 0), 1);
  assert.equal(readdirSync(join(workspace, 'drafts')).length, 1);
  assert.equal(readdirSync(join(workspace, 'receipts')).length, 1);
});

test('a restarted cycle reclaims a dead owner and completes its request', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-restart-test-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const workspace = join(scratch, 'queue');
  const register = join(scratch, 'quotes.csv');
  const fixture = join(scratch, 'fixture.json');
  const input = JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] });
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  writeFileSync(fixture, input);
  const args = ['--workspace', workspace, '--register', register, '--fixture', fixture];
  const setup = spawnSync(process.execPath, [job, 'onboard', ...args], { cwd: repo, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  writeFileSync(join(workspace, 'inbox', 'a.json'), input);
  const inputSha = createHash('sha256').update(input).digest('hex');
  const registerSha = createHash('sha256').update(readFileSync(register)).digest('hex');
  const key = createHash('sha256').update(`keller-job-v1\n${inputSha}\n${registerSha}`).digest('hex');
  const stale = join(workspace, 'claims', key);
  mkdirSync(stale);
  writeFileSync(join(stale, 'owner.json'), JSON.stringify({
    host: hostname(), pid: 2147483647, token: 'dead-owner', started: Date.now(),
  }));
  const restart = spawnSync(process.execPath, [job, 'cycle', ...args], { cwd: repo, encoding: 'utf8' });
  assert.equal(restart.status, 0, restart.stderr);
  assert.deepEqual(JSON.parse(restart.stdout).drafted, ['a.json']);
  assert.equal(existsSync(stale), false);
  assert.equal(existsSync(join(workspace, 'receipts', `${key}.json`)), true);
});

test('old live, foreign, and unknown claims remain busy instead of being stolen', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-claim-safety-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const workspace = join(scratch, 'queue');
  const register = join(scratch, 'quotes.csv');
  const fixture = join(scratch, 'fixture.json');
  const input = JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] });
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  writeFileSync(fixture, input);
  const args = ['--workspace', workspace, '--register', register, '--fixture', fixture];
  const setup = spawnSync(process.execPath, [job, 'onboard', ...args], { cwd: repo, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  writeFileSync(join(workspace, 'inbox', 'a.json'), input);
  const inputSha = createHash('sha256').update(input).digest('hex');
  const registerSha = createHash('sha256').update(readFileSync(register)).digest('hex');
  const key = createHash('sha256').update(`keller-job-v1\n${inputSha}\n${registerSha}`).digest('hex');
  const path = join(workspace, 'claims', key);
  mkdirSync(path);
  const old = Date.now() - 31 * 60_000;
  for (const owner of [
    { host: hostname(), pid: process.pid, token: 'live-owner', started: old },
    { host: 'other-host', pid: 2147483647, token: 'foreign-owner', started: old },
    { host: hostname(), pid: 2147483647, started: old },
  ]) {
    const stored = JSON.stringify(owner);
    writeFileSync(join(path, 'owner.json'), stored);
    const result = spawnSync(process.execPath, [job, 'cycle', ...args], { cwd: repo, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).claimed, ['a.json']);
    assert.equal(readFileSync(join(path, 'owner.json'), 'utf8'), stored);
    assert.equal(readdirSync(join(workspace, 'drafts')).length, 0);
  }
});

test('a worker cannot delete a claim whose owner token changed', async (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-claim-owner-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const workspace = join(scratch, 'queue');
  const register = join(scratch, 'quotes.csv');
  const fixture = join(scratch, 'fixture.json');
  const input = JSON.stringify({ parts: [{ part_no: 'ABC', quantity: 10 }] });
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PLATE,C1,won,10,10\n');
  writeFileSync(fixture, input);
  const args = ['--workspace', workspace, '--register', register, '--fixture', fixture];
  const setup = spawnSync(process.execPath, [job, 'onboard', ...args], { cwd: repo, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  writeFileSync(join(workspace, 'inbox', 'a.json'), input);
  const child = spawn(process.execPath, [job, 'cycle', ...args], { cwd: repo });
  let stdout = ''; let stderr = '';
  child.stdout.on('data', (chunk) => { stdout += chunk; });
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  let path;
  for (let i = 0; i < 200; i++) {
    const names = readdirSync(join(workspace, 'claims')).filter((name) => !name.endsWith('.recovery'));
    if (names.length && existsSync(join(workspace, 'claims', names[0], 'owner.json'))) {
      path = join(workspace, 'claims', names[0]);
      break;
    }
    await new Promise((done) => setTimeout(done, 10));
  }
  assert.ok(path, 'worker never acquired its claim');
  const owner = JSON.parse(readFileSync(join(path, 'owner.json'), 'utf8'));
  writeFileSync(join(path, 'owner.json'), JSON.stringify({ ...owner, token: 'replacement-owner' }));
  const exit = await new Promise((done) => child.on('close', done));
  assert.equal(exit, 0, stderr);
  assert.deepEqual(JSON.parse(stdout).drafted, ['a.json']);
  assert.equal(existsSync(path), true);
  assert.equal(JSON.parse(readFileSync(join(path, 'owner.json'), 'utf8')).token, 'replacement-owner');
});
