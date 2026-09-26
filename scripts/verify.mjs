#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const estimator = join(repo, 'estimator');
const fixture = join(estimator, 'examples/request.json');
const cli = join(estimator, 'dist/src/cli.js');
const env = { ...process.env };
delete env.AI_GATEWAY_API_KEY;
delete env.POLYGRES_DATABASE_URL;
delete env.POLYGRES_DIRECT_URL;

const required = (path, instruction) => {
  if (!existsSync(path)) throw new Error(instruction);
  return path;
};

const run = (command, args, cwd, label, stdio = 'inherit') => {
  console.log(`Verifying ${label}...`);
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf8', stdio, maxBuffer: 32 * 1024 * 1024 });
  if (result.error) {
    if (result.error.code === 'ENOENT') throw new Error(`${label}: ${command} not found; install the required runtime first`);
    throw result.error;
  }
  if (result.status !== 0) throw new Error(`${label} failed (exit ${result.status ?? result.signal})`);
  return result.stdout;
};

export const assertPricedQuote = (quote, request) => {
  if (quote?.jev !== 'disabled' || !Array.isArray(quote.lines) ||
    !quote.lines.length || quote.lines.length !== request.parts.length) {
    throw new Error('offline smoke did not return one offline-priced line per fixture part');
  }
  for (const [index, line] of quote.lines.entries()) {
    const quantity = request.parts[index].quantity;
    if (line?.part?.quantity !== quantity || !Number.isFinite(line.unit_price) || line.unit_price <= 0 ||
      !Number.isFinite(line.extended_price) || line.extended_price <= 0 ||
      Math.abs(line.extended_price - line.unit_price * quantity) > 0.005 + quantity * 0.00005) {
      throw new Error(`offline smoke line ${index + 1} is not fully priced`);
    }
  }
  const total = Math.round(quote.lines.reduce((sum, line) => sum + line.extended_price, 0) * 100) / 100;
  if (!Number.isFinite(quote.total) || Math.abs(quote.total - total) > 0.001) {
    throw new Error('offline smoke total does not match priced lines');
  }
};

const main = () => {
  if (Number(process.versions.node.split('.')[0]) < 24) throw new Error('Node 24 or newer is required');
  const args = process.argv.slice(2);
  if (args.length > 1 || (args.length === 1 && args[0] !== '--database')) {
    throw new Error('usage: node scripts/verify.mjs [--database]');
  }

  if (args[0] === '--database') {
    const url = env.KELLER_TEST_DATABASE_URL;
    if (!url) throw new Error('set KELLER_TEST_DATABASE_URL to an explicit disposable local PostgreSQL URL for --database');
    let parsed;
    try { parsed = new URL(url); }
    catch { throw new Error('KELLER_TEST_DATABASE_URL must be a local PostgreSQL URL'); }
    if (!['postgresql:', 'postgres:'].includes(parsed.protocol) ||
      !['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)) {
      throw new Error('KELLER_TEST_DATABASE_URL must point to a disposable local PostgreSQL server');
    }
    try { run('python', ['-c', 'import psycopg'], repo, 'Python psycopg prerequisite', 'pipe'); }
    catch (error) {
      throw new Error(`${error.message}; install Python and dependencies with python -m pip install -r requirements-db.txt`);
    }
    run('python', ['-m', 'unittest', 'discover', '-s', 'tests', '-v'], repo, 'database tests');
    return;
  }

  const vitest = required(join(estimator, 'node_modules/vitest/vitest.mjs'),
    'estimator dependencies missing; run cd estimator && npm ci before verification');
  const tsc = required(join(estimator, 'node_modules/typescript/bin/tsc'),
    'estimator dependencies missing; run cd estimator && npm ci before verification');
  required(fixture, 'offline request fixture missing: estimator/examples/request.json');
  required(join(repo, 'quotes.csv'), 'quote register missing: quotes.csv');
  const estimatorTests = readdirSync(join(estimator, 'test'))
    .filter((name) => name.endsWith('.test.ts')).sort().map((name) => join(estimator, 'test', name));
  if (!estimatorTests.length) throw new Error('no estimator/test/*.test.ts files found');
  run(process.execPath, [vitest, 'run', ...estimatorTests], estimator, 'estimator tests');
  run(process.execPath, [tsc], estimator, 'TypeScript build');
  required(cli, 'compiled estimator CLI missing after build; check the TypeScript build output');
  const output = run(process.execPath, [cli, fixture, '--offline', '--register', join(repo, 'quotes.csv')],
    estimator, 'compiled CLI offline smoke', 'pipe');
  try { assertPricedQuote(JSON.parse(output), JSON.parse(readFileSync(fixture, 'utf8'))); }
  catch (error) { throw new Error(`compiled CLI offline smoke: ${error.message}`); }
  const tests = readdirSync(join(repo, 'scripts/test'))
    .filter((name) => name.endsWith('.test.mjs')).sort().map((name) => join(repo, 'scripts/test', name));
  if (!tests.length) throw new Error('no scripts/test/*.test.mjs files found');
  run(process.execPath, ['--test', ...tests], repo, 'script tests');
};

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); }
  catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
