import test from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { onboard } from '../keller-environment.mjs';
import { readKnowledge } from '../../arsumbris/knowledge/tool.ts';

function fixture(t) {
  const scratch = join(homedir(), '.capy/work');
  mkdirSync(scratch, { recursive: true, mode: 0o700 });
  const root = mkdtempSync(join(scratch, 'keller-environment-synthetic-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return { root, client: join(root, 'client'), binding: join(root, 'binding', 'knowledge.json') };
}

test('onboarding is private, idempotent, and binds the read-only knowledge tool', t => {
  const { client, binding } = fixture(t);
  const first = onboard(client, binding);
  const second = onboard(client, binding);
  assert.equal(first.state, 'PRIVATE_ENVIRONMENT_INITIALIZED');
  assert.equal(second.root, first.root);
  assert.equal(first.customer_release_authorized, false);
  assert.equal(first.live_accuracy, 'NOT_ESTABLISHED');
  assert.equal(first.schedule, 'NOT_ACTIVATED');
  assert.deepEqual(JSON.parse(readFileSync(binding, 'utf8')), { root: join(client, 'knowledge') });
  const files = readdirSync(join(client, 'knowledge'));
  const result = readKnowledge({ workflow: 'quoting', as_of: '2026-10-04' }, binding);
  assert.equal(result.isError, undefined);
  assert.deepEqual(result.content.records, []);
  assert.match(result.content.warning, /blinded/);
  assert.deepEqual(readdirSync(join(client, 'knowledge')), files);
  const batch = readKnowledge({ queries: JSON.stringify([
    { workflow: 'quoting', as_of: '2026-10-04' },
    { workflow: 'quoting', as_of: '2026-10-04', customer_id: 'SYNTHETIC', part_no: 'P-1', revision: 'A' },
  ]) }, binding);
  assert.equal(batch.isError, undefined);
  assert.equal(batch.content.results.length, 2);
  assert.deepEqual(batch.content.results.map(result => result.records), [[], []]);
});

test('onboarding refuses a competing client binding instead of silently replacing it', t => {
  const { root, client, binding } = fixture(t);
  onboard(client, binding);
  assert.throws(() => onboard(join(root, 'other-client'), binding), /existing knowledge binding differs/);
  assert.deepEqual(JSON.parse(readFileSync(binding, 'utf8')), { root: join(client, 'knowledge') });
});

test('unsafe roots and bindings fail closed', t => {
  const { root, client, binding } = fixture(t);
  assert.throws(() => onboard('relative', binding), /absolute/);
  mkdirSync(client, { mode: 0o755 });
  assert.throws(() => onboard(client, binding), /0700/);
  chmodSync(client, 0o700);
  symlinkSync(client, join(root, 'alias'));
  assert.throws(() => onboard(join(root, 'alias'), binding), /0700/);
  onboard(client, binding);
  chmodSync(binding, 0o644);
  assert.equal(readKnowledge({ workflow: 'quoting', as_of: '2026-10-04' }, binding).isError, true);
});

test('the workflow tool never exposes maintenance actions or accepts a caller-selected library', t => {
  const { client, binding } = fixture(t);
  onboard(client, binding);
  for (const query of [
    { action: 'activate', workflow: 'quoting', as_of: '2026-10-04' },
    { workflow: 'operator-evaluation', as_of: '2026-10-04' },
    { workflow: 'quoting', as_of: '2026-10-04', root: client },
    { workflow: 'quoting', as_of: '2026-10-04', limit: 11 },
    { workflow: 'quoting', as_of: '2026-02-30' },
    { queries: '[]' },
    { queries: JSON.stringify(Array(51).fill({ workflow: 'quoting', as_of: '2026-10-04' })) },
    { queries: '[{"workflow":"quoting","as_of":"2026-10-04","action":"activate"}]' },
    { queries: '[{"workflow":"quoting","as_of":"2026-10-04"}]', workflow: 'quoting' },
  ]) assert.equal(readKnowledge(query, binding).isError, true);
  writeFileSync(binding, JSON.stringify({ root: join(client, 'knowledge'), arbitrary: true }), { mode: 0o600 });
  assert.equal(readKnowledge({ workflow: 'quoting', as_of: '2026-10-04' }, binding).isError, true);
});
