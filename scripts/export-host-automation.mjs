#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { isAbsolute, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(fileURLToPath(new URL('..', import.meta.url)));
const safeId = (name, value) => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error(`${name} must be an observed ID`);
  return value;
};
const absolutePath = (name, value) => {
  if (typeof value !== 'string' || /[\r\n]/.test(value) ||
    !(isAbsolute(value) || /^[A-Za-z]:\\/.test(value) || value.startsWith('\\\\'))) {
    throw new Error(`${name} must be an absolute private path`);
  }
  return value;
};

try {
  if (process.argv.length !== 3) throw new Error('usage: node scripts/export-host-automation.mjs <private-observed-config.json>');
  const config = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const owner = safeId('owner_user_id', config.owner_user_id);
  const workspace = safeId('workspace_id', config.workspace_id);
  const thread = safeId('observed_thread.thread_id', config.observed_thread?.thread_id);
  if (safeId('observed_thread.owner_user_id', config.observed_thread?.owner_user_id) !== owner ||
    safeId('observed_thread.workspace_id', config.observed_thread?.workspace_id) !== workspace) {
    throw new Error('observed thread owner/workspace does not match the approved private binding');
  }
  if (config.repository !== 'OpulentiaAI/keller-quotes' || config.ref !== 'main') {
    throw new Error('repository/ref must explicitly target the authorized Keller main checkout');
  }
  if (typeof config.name !== 'string' || !config.name.trim() || /[\r\n]/.test(config.name)) {
    throw new Error('name must be an approved automation name');
  }
  const runtime = absolutePath('runtime_workspace', config.runtime_workspace);
  const register = absolutePath('register_path', config.register_path);
  const configPath = resolve(process.argv[2]);
  if (!configPath.startsWith(resolve(runtime) + sep)) {
    throw new Error('private host config must live under the persistent runtime workspace');
  }
  const recurrence = config.recurrence;
  const match = typeof recurrence === 'string' && recurrence.match(
    /^DTSTART;TZID=([A-Za-z0-9_+\-]+(?:\/[A-Za-z0-9_+\-]+)+):(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\nRRULE:FREQ=DAILY;BYHOUR=(\d{1,2});BYMINUTE=(\d{1,2})$/,
  );
  if (!match) throw new Error('recurrence must be an approved daily DTSTART;TZID=IANA + RRULE; no UTC conversion');
  const [, zone, year, month, day, hour, minute, second, byHour, byMinute] = match;
  try { new Intl.DateTimeFormat('en-US', { timeZone: zone }); }
  catch { throw new Error('recurrence timezone must be an IANA zone'); }
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (date.toISOString().slice(0, 10) !== `${year}-${month}-${day}` || Number(hour) > 23 ||
    Number(minute) > 59 || Number(second) > 59 || Number(byHour) !== Number(hour) ||
    Number(byMinute) !== Number(minute)) throw new Error('recurrence date/time and daily hour/minute must agree');

  let prompt = readFileSync(resolve(repo, 'docs/host-automation-prompt.md'), 'utf8');
  const fields = { OWNER: owner, WORKSPACE: workspace, THREAD: thread, REPO: config.repository,
    REF: config.ref, RUNTIME: runtime, REGISTER: register, CONFIG: configPath };
  for (const [name, value] of Object.entries(fields)) prompt = prompt.replaceAll(`{{${name}}}`, value);
  if (/{{[A-Z]+}}/.test(prompt)) throw new Error('canonical host prompt contains unresolved fields');
  console.log(JSON.stringify({ readiness: 'HOST_EXPORT_ONLY_LIVE_UNVERIFIED',
    create_thread_if_needed: { action: 'create_thread', workspaceId: workspace, title: config.name },
    inspect_live_schemas: { action: 'schemas', event_type: 'schedule:recurring', action_type: 'message_session' },
    automation_manage_create: {
      action: 'create', name: config.name, enabled: false,
      triggers: [{ event_type: 'schedule:recurring', conditions: { any: [{ all: [
        { field: 'rrule', operator: 'recurrence', value: recurrence },
      ] }] }, replies: [] }],
      actions: [{ type: 'message_session', target_session_id: thread, prompt }],
    },
  }, null, 2));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 2;
}
