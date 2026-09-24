import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';

const repo = join(dirname(fileURLToPath(import.meta.url)), '../..');
const scratch = mkdtempSync(join(tmpdir(), 'keller-eval-test-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const csv = join(scratch, 'register.csv');
const evalset = join(scratch, 'evalset.jsonl');
const report = join(scratch, 'report.md');
const run = (extra: string[] = []) => {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  return spawnSync(join(repo, 'estimator/node_modules/.bin/tsx'),
    [join(repo, 'evals/run-eval.ts'), evalset, '--register', csv, '--report', report, ...extra],
    { cwd: repo, env, encoding: 'utf8' });
};

describe('historical evaluation', () => {
  it('uses a quote-date cutoff by default and handles zero coverage without fake metrics', () => {
    writeFileSync(csv, 'quote_no,item_no,quote_date,part_no,description,customer_id,status,quantity,unit_price\nQ1,,2024-01-01,ABC,PART,C1,open,10,10\nQ2,,2025-01-01,ABC,PART,C1,won,10,20\n');
    writeFileSync(evalset, JSON.stringify({ id: 'Q1@10', source_quote_no: 'Q1', input: {
      part_no: 'ABC', quantity: 10, customer_id: 'C1' }, actual_unit_price: 10,
      quote_date: '2024-01-01', status: 'open' }) + '\n');
    const res = run();
    expect(res.status, res.stderr).toBe(0);
    const json = JSON.parse(readFileSync(report.replace(/\.md$/, '.json'), 'utf8'));
    expect(json.summary).toMatchObject({ cases: 1, priced: 0, no_analog: 1, coverage: 0,
      median_ape: null, mean_ape: null, within_20pct: null });
    expect(readFileSync(report, 'utf8')).toContain('| median APE | n/a |');
    expect(run(['--retrospective']).status).toBe(0);
    const retrospective = JSON.parse(readFileSync(report.replace(/\.md$/, '.json'), 'utf8'));
    expect(retrospective.summary).toMatchObject({ cases: 1, priced: 1, no_analog: 0 });
    expect(retrospective.summary.mode).toMatch(/future data visible/);
  });
  it('marks undated cases unreplayable rather than crashing', () => {
    writeFileSync(evalset, JSON.stringify({ id: 'undated', source_quote_no: 'Q1', input: {
      part_no: 'ABC', quantity: 10 }, actual_unit_price: 10, quote_date: '', status: 'open' }) + '\n');
    const res = run();
    expect(res.status, res.stderr).toBe(0);
    const json = JSON.parse(readFileSync(report.replace(/\.md$/, '.json'), 'utf8'));
    expect(json.summary).toMatchObject({ cases: 1, priced: 0, unreplayable: 1, median_ape: null });
  });
  it('reports an empty input as n/a instead of NaN', () => {
    writeFileSync(evalset, '');
    const res = run();
    expect(res.status, res.stderr).toBe(0);
    const json = JSON.parse(readFileSync(report.replace(/\.md$/, '.json'), 'utf8'));
    expect(json.summary).toMatchObject({ cases: 0, priced: 0, coverage: null, median_ape: null,
      mean_confidence: null });
  });
});
