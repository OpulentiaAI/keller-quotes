import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { assertPricedQuote } from '../verify.mjs';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const verifier = join(repo, 'scripts/verify.mjs');
const run = (args, url, path = process.env.PATH) => {
  const env = { ...process.env };
  delete env.KELLER_TEST_DATABASE_URL;
  if (url !== undefined) env.KELLER_TEST_DATABASE_URL = url;
  for (const key of Object.keys(env)) {
    if (key.toLowerCase() === 'path') env[key] = path;
  }
  env.PATH = path;
  return spawnSync(process.execPath, [verifier, ...args], { cwd: repo, env, encoding: 'utf8' });
};

test('rejects unknown modes before running any suite', () => {
  for (const args of [['--unknown'], ['--database', '--unknown']]) {
    const result = run(args);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /usage: node scripts\/verify\.mjs \[--database\]/);
    assert.equal(result.stdout, '');
  }
});

test('database mode refuses missing and nonlocal test URLs before Python runs', () => {
  const missing = run(['--database']);
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /set KELLER_TEST_DATABASE_URL/);
  assert.equal(missing.stdout, '');

  for (const url of ['not a URL', 'postgresql://example.com/test', 'https://localhost/test']) {
    const result = run(['--database'], url);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /KELLER_TEST_DATABASE_URL must/);
    assert.equal(result.stderr.includes(url), false);
    assert.equal(result.stdout, '');
  }
});

test('database mode reports missing Python without printing the test URL', () => {
  const url = 'postgresql://user:private-password@127.0.0.1/test';
  const result = run(['--database'], url, '');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /install Python and dependencies/);
  assert.equal(result.stderr.includes(url), false);
  assert.equal(result.stderr.includes('private-password'), false);
});

test('offline smoke requires a priced line per input and a consistent total', () => {
  const request = { parts: [{ quantity: 2 }, { quantity: 3 }] };
  const quote = { jev: 'disabled', lines: [
    { part: { quantity: 2 }, unit_price: 1.25, extended_price: 2.5 },
    { part: { quantity: 3 }, unit_price: 2, extended_price: 6 },
  ], total: 8.5 };
  assert.doesNotThrow(() => assertPricedQuote(quote, request));
  assert.doesNotThrow(() => assertPricedQuote({ jev: 'disabled',
    lines: [{ part: { quantity: 1500 }, unit_price: 1.8248, extended_price: 2737.22 }],
    total: 2737.22 }, { parts: [{ quantity: 1500 }] }));
  for (const bad of [
    { ...quote, jev: 'enabled' },
    { ...quote, lines: quote.lines.slice(0, 1) },
    { ...quote, lines: [{ ...quote.lines[0], unit_price: null }, quote.lines[1]] },
    { ...quote, lines: [{ ...quote.lines[0], extended_price: null }, quote.lines[1]] },
    { ...quote, lines: [{ ...quote.lines[0], extended_price: 2 }, quote.lines[1]] },
    { ...quote, total: 0 },
  ]) assert.throws(() => assertPricedQuote(bad, request), /offline smoke/);
});
