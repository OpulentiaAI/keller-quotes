#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const local = join(repo, '.keller-local/learning');
const python = join(local, 'python/bin/python');
const inputs = ['estimator/package.json', 'estimator/package-lock.json',
  'requirements-db.txt', 'requirements-documents.txt'];

function run(command, args, cwd = repo) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', timeout: 600000 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`bootstrap command failed: ${command} (exit ${result.status ?? result.signal})`);
}

export function bootstrap() {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node 24 or newer is required');
  mkdirSync(local, { recursive: true, mode: 0o700 });
  const stamp = join(local, 'dependencies.sha256');
  const hash = createHash('sha256').update(`node:${process.versions.node.split('.')[0]}\n`);
  for (const path of inputs) hash.update(path).update('\0').update(readFileSync(join(repo, path))).update('\0');
  const digest = hash.digest('hex');
  const changed = !existsSync(stamp) || readFileSync(stamp, 'utf8').trim() !== digest ||
    !existsSync(join(repo, 'estimator/node_modules/tsx/dist/cli.mjs')) || !existsSync(python);
  if (changed) {
    run('npm', ['ci'], join(repo, 'estimator'));
    if (!existsSync(python)) run('python3', ['-m', 'venv', join(local, 'python')]);
    run(python, ['-m', 'pip', 'install', '-r', 'requirements-documents.txt', '-r', 'requirements-db.txt']);
    const temp = `${stamp}.${process.pid}.tmp`;
    writeFileSync(temp, `${digest}\n`, { flag: 'wx', mode: 0o600 });
    renameSync(temp, stamp);
  }
  const lock = JSON.parse(readFileSync(join(repo, 'arsumbris/runtime-lock.json'), 'utf8'));
  const history = spawnSync('git', ['cat-file', '-e', `${lock.hostOverlay.commit}^{commit}`], { cwd: repo, stdio: 'ignore' });
  if (history.status !== 0) {
    const shallow = spawnSync('git', ['rev-parse', '--is-shallow-repository'], { cwd: repo, encoding: 'utf8' });
    if (shallow.status !== 0) throw new Error('cannot inspect required pinned history');
    run('git', shallow.stdout.trim() === 'true' ? ['fetch', '--unshallow', 'origin'] : ['fetch', 'origin']);
    const check = spawnSync('git', ['cat-file', '-e', `${lock.hostOverlay.commit}^{commit}`], { cwd: repo, stdio: 'ignore' });
    if (check.status !== 0) throw new Error('required pinned overlay history remains unavailable');
  }
  run('npm', ['run', 'build'], join(repo, 'estimator'));
  run(python, ['-c', 'import anydoc, psycopg, dbfread']);
  return { state: 'DEPENDENCIES_READY', installed: changed, python,
    database_mutations: 0, model_calls: 0, client_activation: 'NOT_PERFORMED' };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 2) throw new Error('usage: node scripts/bootstrap-keller.mjs');
    console.log(JSON.stringify(bootstrap()));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
