import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { beforeScopedCall, loadEvaluationScope, scopedToolList } from '../mcp-evaluation-scope.mjs';

test('existing blind scopes deny the new knowledge library and hide it from discovery', t => {
  const root = mkdtempSync(join(tmpdir(), 'keller-knowledge-isolation-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const path = join(root, 'scope.json');
  const scope = {
    schema_version: 1, case_id: 'synthetic-isolation', corpus: 'a'.repeat(64),
    quote_date: '2025-01-01', excluded_quote_nos: ['SYNTHETIC-TARGET'],
    request: { order_id: 'SYNTHETIC', quote_date: '2025-01-01', customer: 'Synthetic',
      customer_id: 'SYNTHETIC-C', reviewer: 'Synthetic Reviewer',
      parts: [{ line_id: 'line-1', part_no: 'SYNTHETIC-P', quantity: 10 }],
      charges: { shipping: 0, tax: 0 } },
    eligible_prices: [], allowed_files: [],
  };
  writeFileSync(path, JSON.stringify(scope), { mode: 0o600 });
  const guard = loadEvaluationScope(path);
  assert.throws(() => beforeScopedCall('keller_knowledge', {
    workflow: 'quoting', as_of: '2025-01-01', customer_id: 'SYNTHETIC-C',
  }, guard), /unavailable in evaluation scope/);
  assert.deepEqual(scopedToolList({ tools: [
    { name: 'keller_knowledge' }, { name: 'read_file_pinned' },
  ] }, guard).tools.map(tool => tool.name), ['read_file_pinned']);
});
