import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { chmodSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { recordFeedback } from '../keller-feedback.mjs';

function fixture(t) {
  const scratch = join(homedir(), '.capy/work');
  mkdirSync(scratch, { recursive: true, mode: 0o700 });
  const base = mkdtempSync(join(scratch, 'keller-feedback-synthetic-'));
  t.after(() => rmSync(base, { recursive: true, force: true }));
  const root = join(base, 'feedback');
  mkdirSync(root, { mode: 0o700 });
  const request = { order_id: 'SYNTHETIC', parts: [{ line_id: 'line-1', part_no: 'P-1', quantity: 10 }] };
  const request_file = join(base, 'request.json');
  writeFileSync(request_file, JSON.stringify(request), { mode: 0o600 });
  const draft = { schema_version: 1, request, lines: [{ line_id: 'line-1' }], state: 'PRICED_REQUIRES_REVIEW',
    requires_human_review: true, provenance: { request_sha256: createHash('sha256').update(JSON.stringify(request)).digest('hex') } };
  const draft_file = join(base, 'order.json');
  writeFileSync(draft_file, JSON.stringify(draft), { mode: 0o600 });
  return { root, request_file, draft_file, reviewer: 'Synthetic Reviewer', disposition: 'CORRECTION_REQUIRED',
    reason: 'Operator supplied a supported correction', lines: [{ line_id: 'line-1', reviewed_unit_price: 5, reason: 'Synthetic reviewed price' }] };
}

test('feedback binds immutable request/draft bytes and stays separate from knowledge and live accuracy', t => {
  const input = fixture(t);
  const first = recordFeedback(input);
  assert.equal(first.duplicate, false);
  assert.equal(recordFeedback(input).duplicate, true);
  assert.equal(first.customer_release_authorized, false);
  assert.equal(first.independent_live_accuracy, 'NOT_ESTABLISHED');
  const bundle = JSON.parse(readFileSync(join(input.root, `${first.feedback_id}.json`), 'utf8'));
  assert.equal(bundle.payload.kind, 'OPERATOR_FEEDBACK_NOT_KNOWLEDGE');
  assert.deepEqual(Buffer.from(bundle.request.artifact, 'base64'), readFileSync(input.request_file));
  assert.deepEqual(Buffer.from(bundle.draft.artifact, 'base64'), readFileSync(input.draft_file));
});

test('timed-out and failed attempts remain recordable without a draft or fabricated zero', t => {
  const input = fixture(t);
  delete input.draft_file;
  input.lines = [];
  input.disposition = 'TIMED_OUT';
  const result = recordFeedback(input);
  const bundle = JSON.parse(readFileSync(join(input.root, `${result.feedback_id}.json`), 'utf8'));
  assert.equal(bundle.draft, null);
  assert.equal(bundle.payload.draft_sha256, null);
  assert.deepEqual(bundle.payload.lines, []);
});

test('malformed requests remain in the operator ledger as invalid attempts', t => {
  const input = fixture(t);
  delete input.draft_file;
  input.lines = [];
  input.disposition = 'INVALID';
  writeFileSync(input.request_file, '{invalid synthetic request');
  const result = recordFeedback(input);
  const bundle = JSON.parse(readFileSync(join(input.root, `${result.feedback_id}.json`), 'utf8'));
  assert.equal(Buffer.from(bundle.request.artifact, 'base64').toString('utf8'), '{invalid synthetic request');
  assert.equal(bundle.draft, null);
  assert.throws(() => recordFeedback({ ...input, disposition: 'APPROVED_FOR_HUMAN_HANDOFF' }));
});

test('blocked drafts, mismatched identities, unknown lines and invalid prices fail closed', t => {
  const input = fixture(t);
  for (const changes of [
    { lines: [{ line_id: 'other-line', reason: 'Wrong line' }] },
    { lines: [{ line_id: 'line-1', reviewed_unit_price: 0, reason: 'No price' }] },
    { lines: [{ line_id: 'line-1', reviewed_unit_price: '5', reason: 'String price' }] },
    { reason: 'password=synthetic-value' },
  ]) assert.throws(() => recordFeedback({ ...input, ...changes }));
  const draft = JSON.parse(readFileSync(input.draft_file));
  draft.state = 'BLOCKED';
  writeFileSync(input.draft_file, JSON.stringify(draft));
  assert.throws(() => recordFeedback({ ...input, disposition: 'APPROVED_FOR_HUMAN_HANDOFF' }), /blocked/);
  draft.request.parts[0].quantity = 20;
  writeFileSync(input.draft_file, JSON.stringify(draft));
  assert.throws(() => recordFeedback(input), /provenance mismatch/);
});

test('stored feedback cannot be silently overwritten after tampering', t => {
  const input = fixture(t);
  const first = recordFeedback(input);
  writeFileSync(join(input.root, `${first.feedback_id}.json`), '{}');
  assert.throws(() => recordFeedback(input), /mismatch/);
});

test('symlink roots, writable ancestors and nonprivate inputs are rejected', t => {
  const input = fixture(t);
  const linked = join(input.root, '..', 'linked');
  symlinkSync(input.root, linked);
  assert.throws(() => recordFeedback({ ...input, root: linked }), /unsafe/);
  chmodSync(input.request_file, 0o644);
  assert.throws(() => recordFeedback(input), /private artifact/);
  chmodSync(input.request_file, 0o600);
  chmodSync(join(input.root, '..'), 0o777);
  assert.throws(() => recordFeedback(input), /untrusted/);
  chmodSync(join(input.root, '..'), 0o700);
});
