#!/usr/bin/env node
import { chmodSync, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { KnowledgeStore } from './keller-knowledge.mjs';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const binding = join(repo, '.keller-local/arsumbris/knowledge.json');

export function onboard(root, bindingPath = binding) {
  if (typeof root !== 'string' || !isAbsolute(root) || resolve(root) !== root ||
      root === repo || root.startsWith(repo + '/')) throw new Error('explicit absolute private root outside checkout required');
  if (!existsSync(root)) mkdirSync(root, { mode: 0o700 });
  const stat = lstatSync(root);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() ||
      (stat.mode & 0o077) || realpathSync(root) !== root) throw new Error('private root must be owner-bound and mode 0700');
  new KnowledgeStore(root, { readOnly: true });
  for (const name of ['knowledge', 'improvement', 'feedback', 'requests']) {
    const path = join(root, name);
    if (!existsSync(path)) mkdirSync(path, { mode: 0o700 });
    const entry = lstatSync(path);
    if (!entry.isDirectory() || entry.isSymbolicLink() || entry.uid !== process.getuid() ||
        (entry.mode & 0o077)) throw new Error('unsafe environment directory');
  }
  const store = new KnowledgeStore(join(root, 'knowledge'));
  store.search({ workflow: 'quoting', as_of: new Date().toISOString().slice(0, 10), limit: 1 });
  const value = { root: join(root, 'knowledge') };
  if (!isAbsolute(bindingPath) || resolve(bindingPath) !== bindingPath) throw new Error('unsafe knowledge binding path');
  mkdirSync(dirname(bindingPath), { recursive: true, mode: 0o700 });
  if (realpathSync(dirname(bindingPath)) !== dirname(bindingPath) || lstatSync(dirname(bindingPath)).uid !== process.getuid() ||
      (lstatSync(dirname(bindingPath)).mode & 0o077)) throw new Error('unsafe knowledge binding directory');
  if (existsSync(bindingPath)) {
    const prior = lstatSync(bindingPath);
    if (!prior.isFile() || prior.isSymbolicLink() || prior.nlink !== 1 || prior.uid !== process.getuid() ||
        (prior.mode & 0o077) || JSON.stringify(JSON.parse(readFileSync(bindingPath, 'utf8'))) !== JSON.stringify(value)) {
      throw new Error('existing knowledge binding differs or is unsafe; reconcile it explicitly');
    }
  } else writeFileSync(bindingPath, JSON.stringify(value) + '\n', { flag: 'wx', mode: 0o600 });
  chmodSync(bindingPath, 0o600);
  return { state: 'PRIVATE_ENVIRONMENT_INITIALIZED', root, knowledge: 'OWNER_BOUND_READ_ONLY_MCP',
    client_runtime: 'UNVERIFIED', schedule: 'NOT_ACTIVATED', live_accuracy: 'NOT_ESTABLISHED',
    customer_release_authorized: false };
}

export function verify() {
  const python = join(repo, '.keller-local/learning/python/bin');
  if (!existsSync(join(python, 'python'))) throw new Error('run node scripts/bootstrap-keller.mjs first');
  const result = spawnSync(process.execPath, [join(repo, 'scripts/verify.mjs')], {
    cwd: repo, stdio: 'inherit', timeout: 900000,
    env: { ...process.env, PATH: `${python}:${process.env.PATH}` },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`verification failed (${result.status ?? result.signal})`);
  return { state: 'LOCAL_VERIFICATION_PASSED', live_accuracy: 'NOT_ESTABLISHED' };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [action, flag, root, ...extra] = process.argv.slice(2);
    if (action === 'onboard' && flag === '--root' && root && !extra.length) console.log(JSON.stringify(onboard(root)));
    else if (action === 'verify' && flag === undefined) console.log(JSON.stringify(verify()));
    else throw new Error('usage: node scripts/keller-environment.mjs <verify|onboard --root /private/client-environment>');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
