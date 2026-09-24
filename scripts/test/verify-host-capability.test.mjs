import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const verifier = join(repo, 'scripts/verify-host-capability.mjs');

test('fresh second-run read-only proof renews a prior persisted capability receipt', (t) => {
  const runtime = mkdtempSync(join(tmpdir(), 'keller-host-capability-'));
  t.after(() => rmSync(runtime, { recursive: true, force: true }));
  const register = join(runtime, 'quotes.csv');
  const configPath = join(runtime, 'host-config.json');
  const observedPath = join(runtime, 'observed.json');
  const config = { owner_user_id: 'owner_123', workspace_id: 'client_workspace_456',
    observed_thread: { thread_id: 'bound_thread_789', owner_user_id: 'owner_123', workspace_id: 'client_workspace_456' },
    repository: 'OpulentiaAI/keller-quotes', ref: 'main', runtime_workspace: runtime, register_path: register };
  writeFileSync(register, 'fixture');
  writeFileSync(configPath, JSON.stringify(config));
  const observed = { owner_user_id: config.owner_user_id, workspace_id: config.workspace_id,
    thread_id: config.observed_thread.thread_id, repository: config.repository, ref: config.ref,
    runtime_workspace: runtime, register_path: register, checkout_sha: 'a'.repeat(40),
    source_tool: 'read-only-host-observation', read_only: true,
    observed_at: new Date().toISOString(),
    authenticated_read: { status: 'success', source_tool: 'read-only-host-observation',
      action: 'inspect_workspace_binding', result_sha256: 'c'.repeat(64) } };
  const run = () => spawnSync(process.execPath, [verifier, configPath, observedPath],
    { cwd: repo, encoding: 'utf8' });
  writeFileSync(observedPath, JSON.stringify(observed));
  const first = run();
  assert.equal(first.status, 0, first.stderr);
  const latest = join(runtime, 'capabilities/latest.json');
  const previous = JSON.parse(readFileSync(latest, 'utf8'));
  assert.equal(previous.state, 'OBSERVATION_VALIDATED_FOR_THIS_RUN');
  assert.equal(previous.provider_auth_valid_until, null);
  assert.ok(Date.parse(previous.observation_fresh_until) > Date.parse(previous.observed_at));
  writeFileSync(latest, JSON.stringify({ ...previous, verified_at: '2000-01-01T00:00:00.000Z' }));
  const next = { ...observed, checkout_sha: 'b'.repeat(40),
    observed_at: new Date().toISOString() };
  writeFileSync(observedPath, JSON.stringify(next));
  const second = run();
  assert.equal(second.status, 0, second.stderr);
  const renewed = JSON.parse(readFileSync(latest, 'utf8'));
  assert.equal(renewed.checkout_sha, 'b'.repeat(40));
  assert.notEqual(renewed.verified_at, '2000-01-01T00:00:00.000Z');
  assert.equal(renewed.owner_user_id, config.owner_user_id);
  const stable = readFileSync(latest, 'utf8');

  writeFileSync(observedPath, JSON.stringify({ ...next, owner_user_id: 'different_owner' }));
  assert.equal(run().status, 2);
  assert.equal(readFileSync(latest, 'utf8'), stable);
  writeFileSync(observedPath, JSON.stringify({ ...next,
    auth_valid_until: new Date(Date.now() - 1000).toISOString() }));
  assert.equal(run().status, 2);
  assert.equal(readFileSync(latest, 'utf8'), stable);
  writeFileSync(observedPath, JSON.stringify({ ...next, authenticated_read: undefined }));
  assert.equal(run().status, 2);
  assert.equal(readFileSync(latest, 'utf8'), stable);
  writeFileSync(observedPath, JSON.stringify({ ...next,
    authenticated_read: { ...next.authenticated_read, status: 'failure' } }));
  assert.equal(run().status, 2);
  assert.equal(readFileSync(latest, 'utf8'), stable);
});
