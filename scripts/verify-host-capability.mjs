#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const writeAtomic = (path, contents) => {
  const temp = `${path}.${process.pid}.${Math.random().toString(16).slice(2)}.tmp`;
  writeFileSync(temp, contents, { flag: 'wx' });
  renameSync(temp, path);
};

try {
  if (process.argv.length !== 4) throw new Error('usage: node scripts/verify-host-capability.mjs <private-config.json> <fresh-host-observation.json>');
  const configBytes = readFileSync(process.argv[2]);
  const observationBytes = readFileSync(process.argv[3]);
  const config = JSON.parse(configBytes);
  const observed = JSON.parse(observationBytes);
  const identity = {
    owner_user_id: config.owner_user_id,
    workspace_id: config.workspace_id,
    thread_id: config.observed_thread?.thread_id,
    repository: config.repository,
    ref: config.ref,
    runtime_workspace: config.runtime_workspace,
    register_path: config.register_path,
  };
  if (config.observed_thread?.owner_user_id !== identity.owner_user_id ||
    config.observed_thread?.workspace_id !== identity.workspace_id ||
    Object.values(identity).some((value) => typeof value !== 'string' || !value)) {
    throw new Error('private expected binding is incomplete or internally inconsistent');
  }
  for (const [name, expected] of Object.entries(identity)) {
    if (observed[name] !== expected) throw new Error(`read-only observation differs from approved ${name}`);
  }
  if (!/^[0-9a-f]{40}$/.test(observed.checkout_sha) ||
    typeof observed.source_tool !== 'string' || !observed.source_tool.trim() ||
    observed.read_only !== true || !existsSync(identity.runtime_workspace) || !existsSync(identity.register_path)) {
    throw new Error('read-only checkout/runtime/register observation is incomplete');
  }
  const probe = observed.authenticated_read;
  if (probe?.status !== 'success' || probe.source_tool !== observed.source_tool ||
    typeof probe.action !== 'string' || !probe.action.trim() ||
    !/^[0-9a-f]{64}$/.test(probe.result_sha256)) {
    throw new Error('successful authenticated read-only host probe with result digest is required');
  }
  const now = Date.now();
  const observedAt = Date.parse(observed.observed_at);
  if (!Number.isFinite(observedAt) || observedAt < now - 5 * 60_000 || observedAt > now + 60_000) {
    throw new Error('read-only observation is stale or future-dated');
  }
  const providerExpiry = observed.auth_valid_until;
  if (providerExpiry !== undefined &&
    (typeof providerExpiry !== 'string' || !Number.isFinite(Date.parse(providerExpiry)) ||
      Date.parse(providerExpiry) <= now)) {
    throw new Error('provider-reported auth expiry is invalid or expired');
  }
  const capabilities = join(identity.runtime_workspace, 'capabilities');
  mkdirSync(capabilities, { recursive: true });
  const latest = join(capabilities, 'latest.json');
  if (existsSync(latest)) {
    const prior = JSON.parse(readFileSync(latest, 'utf8'));
    for (const [name, expected] of Object.entries(identity)) {
      if (prior[name] !== expected) throw new Error(`prior private capability binding differs on ${name}`);
    }
  }
  const receipt = { state: 'OBSERVATION_VALIDATED_FOR_THIS_RUN', ...identity,
    checkout_sha: observed.checkout_sha, source_tool: observed.source_tool,
    authenticated_read: probe, observed_at: observed.observed_at,
    observation_fresh_until: new Date(observedAt + 5 * 60_000).toISOString(),
    provider_auth_valid_until: providerExpiry ?? null,
    verified_at: new Date(now).toISOString(), config_sha256: sha(configBytes),
    observation_sha256: sha(observationBytes) };
  writeAtomic(latest, JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ state: receipt.state, verified_at: receipt.verified_at,
    observation_fresh_until: receipt.observation_fresh_until, receipt_file: latest }));
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 2;
}
