import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const exporter = join(repo, 'scripts/export-host-automation.mjs');
const config = {
  name: 'Keller offline draft job', owner_user_id: 'owner_123', workspace_id: 'client_workspace_456',
  observed_thread: { thread_id: 'bound_thread_789', owner_user_id: 'owner_123', workspace_id: 'client_workspace_456' },
  repository: 'OpulentiaAI/keller-quotes', ref: 'main',
  runtime_workspace: '/private/client-keller/quote-jobs', register_path: '/private/client-keller/quotes.csv',
  recurrence: 'DTSTART;TZID=America/New_York:20261015T090000\nRRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=0',
};

test('exports a disabled named-zone job to the same observed bound thread on repeat', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-host-export-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const path = join(scratch, 'private.json');
  const privateConfig = { ...config, runtime_workspace: scratch, register_path: join(scratch, 'quotes.csv') };
  writeFileSync(path, JSON.stringify(privateConfig));
  const run = () => spawnSync(process.execPath, [exporter, path], { cwd: repo, encoding: 'utf8' });
  const first = run();
  const second = run();
  assert.equal(first.status, 0, first.stderr);
  assert.equal(second.status, 0, second.stderr);
  assert.equal(first.stdout, second.stdout);
  const result = JSON.parse(first.stdout);
  assert.equal(result.readiness, 'HOST_EXPORT_ONLY_LIVE_UNVERIFIED');
  assert.deepEqual(result.create_thread_if_needed, {
    action: 'create_thread', workspaceId: config.workspace_id, title: config.name,
  });
  assert.deepEqual(result.inspect_live_schemas, {
    action: 'schemas', event_type: 'schedule:recurring', action_type: 'message_session',
  });
  const create = result.automation_manage_create;
  assert.equal(create.action, 'create');
  assert.equal(create.enabled, false);
  assert.deepEqual(create.triggers, [{ event_type: 'schedule:recurring', conditions: { any: [{ all: [
    { field: 'rrule', operator: 'recurrence', value: config.recurrence },
  ] }] }, replies: [] }]);
  assert.equal(create.actions.length, 1);
  assert.equal(create.actions[0].type, 'message_session');
  assert.equal(create.actions[0].target_session_id, config.observed_thread.thread_id);
  assert.equal(create.actions[0].prompt.includes('At the start of **every** invocation'), true);
  assert.equal(create.actions[0].prompt.includes(privateConfig.runtime_workspace), true);
  assert.equal(create.actions[0].prompt.includes(path), true);
  assert.equal(create.actions[0].prompt.includes('{{'), false);
  assert.equal(create.auto_create, undefined);
  assert.equal(readFileSync(join(repo, 'docs/host-automation-prompt.md'), 'utf8').includes('paid calls'), true);
});

test('refuses mismatched identity, wrong repository, and implicit UTC schedules', (t) => {
  const scratch = mkdtempSync(join(tmpdir(), 'keller-host-invalid-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const path = join(scratch, 'private.json');
  for (const invalid of [
    { observed_thread: { ...config.observed_thread, owner_user_id: 'someone_else' } },
    { observed_thread: { ...config.observed_thread, workspace_id: 'wrong_workspace' } },
    { repository: 'Other/repo' },
    { recurrence: 'DTSTART:20261015T090000Z\nRRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=0' },
    { recurrence: 'DTSTART;TZID=America/New_York:20261015T090000\nRRULE:FREQ=DAILY;BYHOUR=10;BYMINUTE=0' },
  ]) {
    writeFileSync(path, JSON.stringify({ ...config, runtime_workspace: scratch,
      register_path: join(scratch, 'quotes.csv'), ...invalid }));
    const result = spawnSync(process.execPath, [exporter, path], { cwd: repo, encoding: 'utf8' });
    assert.equal(result.status, 2);
    assert.equal(result.stdout, '');
  }
});
