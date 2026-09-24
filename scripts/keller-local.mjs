#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { hostname } from 'node:os';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const command = args.shift();
const value = (name, fallback) => {
  const at = args.indexOf(name);
  if (at < 0) return fallback;
  if (!args[at + 1] || args[at + 1].startsWith('--')) throw new Error(`${name} needs a value`);
  return args[at + 1];
};
const register = resolve(value('--register', join(repo, 'quotes.csv')));
const workspace = resolve(value('--workspace', join(repo, '.keller-local')));
const fixture = resolve(value('--fixture', join(repo, 'estimator/examples/request.json')));
const runner = join(repo, 'estimator/node_modules/tsx/dist/cli.mjs');
const cli = join(repo, 'estimator/src/cli.ts');
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const writeAtomic = (path, data) => {
  const tmp = `${path}.${process.pid}.${Math.random().toString(16).slice(2)}.tmp`;
  writeFileSync(tmp, data, { flag: 'wx' });
  renameSync(tmp, path);
};
const estimate = (request) => {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  const result = spawnSync(process.execPath, [runner, cli, request, '--offline', '--register', register], {
    cwd: repo, env, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error((result.stderr || `estimator exit ${result.status}`).trim());
  return JSON.parse(result.stdout);
};
const dir = (name) => join(workspace, name);
const prepare = () => {
  for (const name of ['inbox', 'drafts', 'proofs', 'receipts', 'held', 'claims']) mkdirSync(dir(name), { recursive: true });
};
const claim = (key) => {
  const path = join(dir('claims'), key);
  const token = randomUUID();
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      mkdirSync(path);
      writeFileSync(join(path, 'owner.json'), JSON.stringify({
        pid: process.pid, host: hostname(), token, started: Date.now(),
      }));
      return { path, token };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const recovery = `${path}.recovery`;
      try { mkdirSync(recovery); }
      catch (e) { if (e.code === 'EEXIST') return null; throw e; }
      try {
        const owner = JSON.parse(readFileSync(join(path, 'owner.json'), 'utf8'));
        if (owner.host !== hostname() || !Number.isInteger(owner.pid) ||
          typeof owner.token !== 'string' || !owner.token) return null;
        try { process.kill(owner.pid, 0); return null; }
        catch (e) { if (e.code !== 'ESRCH') return null; }
        const retired = `${path}.${token}.retired`;
        renameSync(path, retired);
        rmSync(retired, { recursive: true, force: true });
      } catch {
        return null;
      } finally {
        rmSync(recovery, { recursive: true, force: true });
      }
    }
  }
  return null;
};
const releaseClaim = (claimOwner) => {
  try {
    const owner = JSON.parse(readFileSync(join(claimOwner.path, 'owner.json'), 'utf8'));
    if (owner.token === claimOwner.token && owner.pid === process.pid && owner.host === hostname()) {
      rmSync(claimOwner.path, { recursive: true, force: true });
    }
  } catch {}
};
const verifyDraft = (key, inputSha, registerSha, bytes, draftPath, proofPath, receiptPath) => {
  if (!existsSync(draftPath) || !existsSync(proofPath)) throw new Error('draft or proof missing');
  const draftBytes = readFileSync(draftPath);
  const proof = JSON.parse(readFileSync(proofPath, 'utf8'));
  if (proof.job_key !== key || proof.input_sha256 !== inputSha || proof.register_sha256 !== registerSha ||
    proof.draft_sha256 !== sha(draftBytes)) throw new Error('draft proof mismatch');
  const request = JSON.parse(bytes.toString('utf8'));
  const draft = JSON.parse(draftBytes.toString('utf8'));
  if (JSON.stringify(draft.request) !== JSON.stringify(request) || draft.jev !== 'disabled' ||
    !Array.isArray(draft.lines) || draft.lines.length !== request.parts?.length) {
    throw new Error('draft request or offline output mismatch');
  }
  if (existsSync(receiptPath)) {
    const receipt = JSON.parse(readFileSync(receiptPath, 'utf8'));
    if (receipt.job_key !== key || receipt.input_sha256 !== inputSha ||
      receipt.register_sha256 !== registerSha || receipt.draft_sha256 !== proof.draft_sha256 ||
      receipt.draft_file !== `drafts/${key}.json` || receipt.state !== 'DRAFT_REQUIRES_MANUAL_REVIEW') {
      throw new Error('receipt mismatch');
    }
  }
  return proof.draft_sha256;
};

try {
  if (!['onboard', 'cycle'].includes(command) || args.length % 2 || args.some((arg, i) =>
    i % 2 === 0 ? !['--register', '--workspace', '--fixture'].includes(arg) : arg.startsWith('--'))) {
    throw new Error('usage: node scripts/keller-local.mjs <onboard|cycle> [--workspace DIR] [--register CSV] [--fixture REQUEST]');
  }
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node 24 or newer is required');
  if (!existsSync(register) || !statSync(register).isFile()) throw new Error(`quote register not found: ${register}`);
  if (!existsSync(runner)) throw new Error('estimator dependencies missing; run cd estimator && npm ci');
  prepare();

  if (command === 'onboard') {
    const quote = estimate(fixture);
    if (quote.lines.length === 0 || quote.lines.some((line) => line.unit_price === null)) {
      throw new Error('local fixture did not produce a fully priced draft');
    }
    console.log(JSON.stringify({ local: 'LOCAL_READY', fixture_lines: quote.lines.length,
      workspace, register,
      runtime_persistence: 'UNVERIFIED', scheduler_workspace_binding: 'UNVERIFIED',
      external: process.env.POLYGRES_DIRECT_URL && process.env.AI_GATEWAY_API_KEY ?
        'INTEGRATION_UNVERIFIED' : 'INTEGRATION_BLOCKED',
      database: process.env.POLYGRES_DIRECT_URL ? 'configured_unverified' : 'missing POLYGRES_DIRECT_URL',
      gateway: process.env.AI_GATEWAY_API_KEY ? 'configured_unverified' : 'missing AI_GATEWAY_API_KEY',
    }));
  } else {
    const registerSha = sha(readFileSync(register));
    const cycle = { drafted: [], duplicate: [], claimed: [], held: [], failed: [] };
    for (const file of readdirSync(dir('inbox'), { withFileTypes: true }).filter((entry) => entry.isFile() && entry.name.endsWith('.json')).sort((a, b) => a.name.localeCompare(b.name))) {
      const input = join(dir('inbox'), file.name);
      const bytes = readFileSync(input);
      const inputSha = sha(bytes);
      const key = sha(`keller-job-v1\n${inputSha}\n${registerSha}`);
      const draft = join(dir('drafts'), `${key}.json`);
      const proof = join(dir('proofs'), `${key}.json`);
      const receipt = join(dir('receipts'), `${key}.json`);
      const held = join(dir('held'), `${key}.json`);
      const lock = claim(key);
      if (!lock) { cycle.claimed.push(file.name); continue; }
      try {
        if (existsSync(held)) { cycle.held.push(file.name); continue; }
        if (existsSync(draft) || existsSync(proof) || existsSync(receipt)) {
          try {
            const draftSha = verifyDraft(key, inputSha, registerSha, bytes, draft, proof, receipt);
            if (existsSync(receipt)) { cycle.duplicate.push(file.name); continue; }
            writeAtomic(receipt, JSON.stringify({ job_key: key, input_sha256: inputSha,
              register_sha256: registerSha, draft_sha256: draftSha, source_file: basename(file.name),
              draft_file: `drafts/${key}.json`, state: 'DRAFT_REQUIRES_MANUAL_REVIEW' }, null, 2) + '\n');
            cycle.drafted.push(file.name);
          } catch (error) {
            writeAtomic(held, JSON.stringify({ job_key: key, input_sha256: inputSha,
              register_sha256: registerSha, source_file: basename(file.name),
              state: 'HELD_AMBIGUOUS_ARTIFACT', reason: error.message }, null, 2) + '\n');
            cycle.held.push(file.name);
          }
          continue;
        }
        const snapshot = join(lock.path, 'input.json');
        writeFileSync(snapshot, bytes, { flag: 'wx' });
        const quote = estimate(snapshot);
        if (sha(readFileSync(register)) !== registerSha) throw new Error('register changed during pricing; retry with its new digest');
        const draftBytes = JSON.stringify(quote, null, 2) + '\n';
        writeAtomic(draft, draftBytes);
        const draftSha = sha(draftBytes);
        writeAtomic(proof, JSON.stringify({ job_key: key, input_sha256: inputSha,
          register_sha256: registerSha, draft_sha256: draftSha }, null, 2) + '\n');
        writeAtomic(receipt, JSON.stringify({ job_key: key, input_sha256: inputSha,
          register_sha256: registerSha, draft_sha256: draftSha, source_file: basename(file.name),
          draft_file: `drafts/${key}.json`, state: 'DRAFT_REQUIRES_MANUAL_REVIEW' }, null, 2) + '\n');
        cycle.drafted.push(file.name);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (message.startsWith('invalid request:')) {
          writeAtomic(held, JSON.stringify({ job_key: key, input_sha256: inputSha,
            register_sha256: registerSha, source_file: basename(file.name),
            state: 'HELD_INVALID_REQUEST', reason: message }, null, 2) + '\n');
          cycle.held.push(file.name);
        } else {
          cycle.failed.push({ file: file.name, reason: message });
        }
      } finally {
        releaseClaim(lock);
      }
    }
    console.log(JSON.stringify(cycle));
    if (cycle.failed.length) process.exitCode = 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 2;
}
