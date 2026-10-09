#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { constants, closeSync, fstatSync, fsyncSync, linkSync, lstatSync, openSync, readFileSync, realpathSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const states = ['APPROVED_FOR_HUMAN_HANDOFF', 'CORRECTION_REQUIRED', 'HELD', 'INVALID', 'FAILED', 'TIMED_OUT'];
const credentials = /(?:postgres(?:ql)?:\/\/|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|api[_-]?key|access[_-]?token|secret)\s*["']?\s*[:=]|\bBearer\s+[A-Za-z0-9._-]+)/i;
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);

function privateDirectory(path) {
  if (typeof path !== 'string' || !isAbsolute(path) || resolve(path) !== path ||
      path === repo || path.startsWith(repo + '/') || realpathSync(path) !== path) throw new Error('unsafe private path');
  const stat = lstatSync(path);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() ||
      (stat.mode & 0o077)) throw new Error('owner-private directory required');
  for (let parent = dirname(path); ; parent = dirname(parent)) {
    const ancestor = lstatSync(parent);
    if (!ancestor.isDirectory() || ancestor.isSymbolicLink() || (ancestor.mode & 0o022) ||
        (ancestor.uid !== 0 && ancestor.uid !== process.getuid())) throw new Error('untrusted private-path ancestor');
    if (parent === dirname(parent)) break;
  }
}

function privateBytes(path) {
  privateDirectory(dirname(path));
  if (resolve(path) !== path || realpathSync(path) !== path) throw new Error('unsafe private file');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() ||
        (stat.mode & 0o077) || stat.size > 4 * 1024 * 1024) throw new Error('invalid private artifact');
    const bytes = readFileSync(fd);
    if (bytes.length !== stat.size) throw new Error('artifact changed during read');
    return bytes;
  } finally { closeSync(fd); }
}

function text(value) {
  return typeof value === 'string' && value.trim() && value.length <= 512 && !/[\x00-\x1f\x7f]/.test(value);
}

export function recordFeedback(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      Object.keys(input).some(key => !['root', 'request_file', 'draft_file', 'reviewer', 'disposition', 'reason', 'lines'].includes(key))) {
    throw new Error('invalid feedback schema');
  }
  privateDirectory(input.root);
  if (!text(input.reviewer) || !text(input.reason) || !states.includes(input.disposition)) throw new Error('named disposition and reason required');
  const requestBytes = privateBytes(input.request_file);
  if (credentials.test(requestBytes.toString('utf8'))) throw new Error('credential-bearing request denied');
  let request;
  try { request = JSON.parse(requestBytes); } catch {
    if (input.disposition !== 'INVALID') throw new Error('invalid request JSON requires INVALID disposition');
  }
  const hasIdentity = request && Array.isArray(request.parts) && request.parts.length > 0 && request.parts.length <= 50 &&
    request.parts.every(part => part && text(part.line_id) && Number.isSafeInteger(part.quantity) && part.quantity > 0) &&
    new Set(request.parts.map(part => part.line_id)).size === request.parts.length;
  if (!hasIdentity && (input.draft_file !== undefined || !['INVALID', 'FAILED', 'TIMED_OUT'].includes(input.disposition))) throw new Error('invalid request identity');
  let draftBytes, draft;
  if (input.draft_file !== undefined) {
    draftBytes = privateBytes(input.draft_file);
    if (credentials.test(draftBytes.toString('utf8'))) throw new Error('credential-bearing draft denied');
    draft = JSON.parse(draftBytes);
    if (draft.schema_version !== 1 || draft.requires_human_review !== true ||
        !['PRICED_REQUIRES_REVIEW', 'BLOCKED'].includes(draft.state) ||
        canonical(draft.request) !== canonical(request) || !Array.isArray(draft.lines) ||
        draft.lines.length !== request.parts.length || draft.lines.some((line, i) => line.line_id !== request.parts[i].line_id) ||
        draft.provenance?.request_sha256 !== sha(JSON.stringify(draft.request))) throw new Error('draft/request provenance mismatch');
  }
  if (['APPROVED_FOR_HUMAN_HANDOFF', 'CORRECTION_REQUIRED', 'HELD'].includes(input.disposition) && !draft) throw new Error('disposition requires observed draft');
  if (input.disposition === 'APPROVED_FOR_HUMAN_HANDOFF' && draft.state !== 'PRICED_REQUIRES_REVIEW') throw new Error('blocked draft cannot be completed');
  const lines = input.lines ?? [];
  if (!Array.isArray(lines) || lines.length > 50 || new Set(lines.map(line => line?.line_id)).size !== lines.length) throw new Error('invalid feedback lines');
  for (const line of lines) {
    if (!line || Object.keys(line).some(key => !['line_id', 'reviewed_unit_price', 'reason'].includes(key)) ||
        !hasIdentity || !request.parts.some(part => part.line_id === line.line_id) || !text(line.reason) ||
        (line.reviewed_unit_price !== undefined && (typeof line.reviewed_unit_price !== 'number' ||
          !Number.isFinite(line.reviewed_unit_price) || line.reviewed_unit_price <= 0))) throw new Error('invalid line correction');
  }
  const payload = { schema_version: 1, kind: 'OPERATOR_FEEDBACK_NOT_KNOWLEDGE',
    request_sha256: sha(requestBytes), draft_sha256: draftBytes ? sha(draftBytes) : null,
    reviewer: input.reviewer, disposition: input.disposition, reason: input.reason, lines,
    independent_live_accuracy: 'NOT_ESTABLISHED', customer_release_authorized: false };
  if (credentials.test(canonical(payload))) throw new Error('credential-bearing feedback denied');
  const key = sha(canonical(payload));
  const bundle = { feedback_id: key, payload, request: { sha256: sha(requestBytes), artifact: requestBytes.toString('base64') },
    draft: draftBytes ? { sha256: sha(draftBytes), artifact: draftBytes.toString('base64') } : null };
  const file = join(input.root, `${key}.json`);
  const bytes = Buffer.from(JSON.stringify(bundle) + '\n');
  let duplicate = false;
  try {
    const prior = privateBytes(file);
    if (!prior.equals(bytes)) throw new Error('feedback artifact mismatch');
    duplicate = true;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    const temp = join(input.root, `.feedback-${randomUUID()}.tmp`);
    const fd = openSync(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
    try {
      try { linkSync(temp, file); }
      catch (failure) {
        if (failure.code !== 'EEXIST' || !privateBytes(file).equals(bytes)) throw failure;
        duplicate = true;
      }
    } finally { unlinkSync(temp); }
    const directory = openSync(input.root, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { fsyncSync(directory); } finally { closeSync(directory); }
  }
  return { feedback_id: key, feedback_sha256: sha(bytes), duplicate,
    disposition: input.disposition, independent_live_accuracy: 'NOT_ESTABLISHED', customer_release_authorized: false };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 2) throw new Error('usage: node scripts/keller-feedback.mjs < private-feedback-input.json');
    const bytes = readFileSync(0);
    if (bytes.length > 128 * 1024) throw new Error('feedback input exceeds budget');
    console.log(JSON.stringify(recordFeedback(JSON.parse(bytes.toString('utf8')))));
  } catch {
    console.error('Feedback invalid or private artifacts unavailable; nothing was approved or released');
    process.exitCode = 1;
  }
}
