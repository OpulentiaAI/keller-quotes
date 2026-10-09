import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, unlinkSync, writeFileSync } from 'node:fs';
import { homedir, hostname } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildSchedule, diagnoseReport, freezePlan, runPlan, statusPlan } from '../keller-improvement.mjs';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const controller = join(repo, 'scripts/keller-improvement.mjs');
const tsx = join(repo, 'estimator/node_modules/tsx/dist/cli.mjs');
const base = join(homedir(), '.capy/work/keller-improvement-tests');
mkdirSync(base, { recursive: true, mode: 0o700 });
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const read = (path) => JSON.parse(readFileSync(path, 'utf8'));
const criteria = ['priced_finite', 'source_excluded', 'cutoff_evidence', 'unit_within_20pct', 'extension_reconciles'];

const fixture = (t, options = {}) => {
  assert.ok(existsSync(tsx), 'Run cd estimator && npm ci first; tests do not mock pricing.');
  const scratch = mkdtempSync(join(base, 'case-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const copy = join(scratch, 'checkout');
  for (const directory of ['estimator/src', '.agents/skills', 'docs', 'arsumbris', 'type', 'profiles', 'skills', 'inject', '.arsumbris']) {
    cpSync(join(repo, directory), join(copy, directory), { recursive: true });
  }
  for (const file of ['estimator/package-lock.json', 'estimator/package.json', 'estimator/tsconfig.json',
    'evals/package.json', 'evals/tsconfig.json', ...readdirSync(join(repo, 'evals')).filter((name) => name.endsWith('.ts')).map((name) => `evals/${name}`),
    ...readdirSync(join(repo, 'scripts')).filter((name) => /\.(mjs|py|sh|ts)$/.test(name)).map((name) => `scripts/${name}`)]) {
    mkdirSync(dirname(join(copy, file)), { recursive: true });
    cpSync(join(repo, file), join(copy, file));
  }
  symlinkSync(join(repo, 'estimator/node_modules'), join(copy, 'estimator/node_modules'), 'dir');
  const register = join(scratch, 'register.csv');
  const evalset = join(scratch, 'cases.jsonl');
  const baseline = join(scratch, 'baseline.json');
  const state_root = join(scratch, 'private');
  writeFileSync(register, 'quote_no,item_no,quote_date,part_no,status,quantity,unit_price\n' +
    'A-old,,2023-01-01,AAAA,open,10,10\nB-old,,2023-01-01,BBBB,open,10,30\n');
  const cases = [
    { id: 'Customer-private-A', source_quote_no: 'A-target', part: 'AAAA', actual: 10 },
    { id: 'Customer-private-B', source_quote_no: 'B-target', part: 'BBBB', actual: 25 },
    { id: 'missing-identity', source_quote_no: '', part: 'AAAA', actual: 10 },
    { id: 'held-no-analog', source_quote_no: 'X-target', part: 'ZZZZ', actual: 10 },
  ].map(({ id, source_quote_no, part, actual }) => ({ id, source_quote_no, quote_date: '2024-01-01', status: 'open',
    input: { part_no: part, quantity: 10 }, actual_unit_price: actual }));
  writeFileSync(evalset, cases.map((item) => JSON.stringify(item)).join('\n') + '\n');
  const generateBaseline = (extra = [], output = join(scratch, 'baseline.md')) => {
    const result = spawnSync(process.execPath, [tsx, join(copy, 'evals/run-eval.ts'), evalset, '--register', register,
      '--report', output, ...extra], { cwd: copy, env: { PATH: '/usr/bin:/bin', TSX_DISABLE_CACHE: '1' }, encoding: 'utf8', timeout: 15000 });
    assert.equal(result.status, 0, result.stderr);
    return output.replace(/\.md$/, '.json');
  };
  generateBaseline();
  return { scratch, copy, register, evalset, baseline, state_root, cases, generateBaseline,
    config: { repo_root: copy, register, evalset, baseline, state_root, command_timeout_ms: 10000, total_timeout_ms: 30000, ...options } };
};
const jobDirectory = (context, frozen) => join(context.state_root, 'jobs', frozen.job_key);
const journal = (directory) => readdirSync(join(directory, 'journal')).sort().map((name) => read(join(directory, 'journal', name)));
const request = (context, frozen, extra = {}) => ({ state_root: context.state_root, job_key: frozen.job_key, ...extra });

test('freezes before execution, runs real eval and compare, and verifies duplicate artifacts', async (t) => {
  const context = fixture(t);
  const frozen = freezePlan(context.config);
  const directory = jobDirectory(context, frozen);
  assert.equal(frozen.state, 'FROZEN');
  assert.deepEqual(journal(directory).map((entry) => entry.event), ['frozen']);
  assert.equal(existsSync(join(directory, 'candidate.json')), false);
  const plan = read(frozen.plan_path);
  assert.deepEqual(plan.identity.selection, {});
  assert.equal(plan.identity.case_count, 4);
  assert.equal(plan.identity.skills.length, readdirSync(join(context.copy, '.agents/skills')).length);
  assert.ok(plan.identity.sources.some((item) => item.path.endsWith('/arsumbris/quote/tool.ts')));
  assert.ok(plan.identity.sources.some((item) => item.path.endsWith('/profiles/Keller Workflow.yaml')));
  assert.ok(plan.identity.sources.some((item) => item.path.endsWith('/estimator/package-lock.json')));
  const again = freezePlan(context.config);
  assert.equal(again.job_key, frozen.job_key);
  assert.equal(again.duplicate, true);
  const result = await runPlan(request(context, frozen));
  assert.equal(result.state, 'COMPLETED');
  assert.deepEqual([result.aggregate.all_case_denominator, result.aggregate.priced, result.aggregate.held, result.aggregate.error], [4, 2, 1, 1]);
  assert.equal(result.aggregate.all_pass_count, 2);
  assert.equal(result.readiness.pipeline_verification, 'VERIFIED');
  assert.equal(result.readiness.goal_over_90_percent, 'UNMET');
  assert.equal(result.readiness.independent_live_accuracy, 'NOT_ESTABLISHED');
  assert.equal(result.aggregate.blind_confirmation, false);
  const events = journal(directory);
  const comparison = events.find((entry) => entry.event === 'command_started' && entry.payload.stage === 'comparison');
  assert.ok(comparison.payload.args.includes('--fail-on-regression'));
  const candidate = read(join(directory, 'candidate.json'));
  assert.equal(candidate.schema_version, 2);
  assert.equal(candidate.provenance.configuration.jev_configured, false);
  const publicBytes = readFileSync(join(directory, 'aggregate.json'), 'utf8');
  assert.ok(!publicBytes.includes('Customer-private'));
  assert.ok(!publicBytes.includes('signed_unit_error'));
  assert.ok(!publicBytes.includes('target_document'));
  for (const name of ['plan.json', 'candidate.json', 'candidate.md', 'comparison-1.md', 'aggregate.json',
    'diagnostics.private.json', 'schedule.json', 'eval-1.stdout', 'eval-1.stderr', 'inputs/register',
    ...readdirSync(join(directory, 'journal')).map((name) => `journal/${name}`)]) {
    assert.equal(statSync(join(directory, name)).mode & 0o777, 0o600, name);
  }
  const count = events.length;
  const duplicate = await runPlan(request(context, frozen));
  assert.equal(duplicate.verified_duplicate, true);
  assert.equal(journal(directory).length, count);
  assert.equal(statusPlan(request(context, frozen)).verified, true);
});

test('rejects unsafe roots, unsupported claims, incompatible baselines and unbounded configuration', (t) => {
  const context = fixture(t);
  for (const changes of [
    { state_root: 'relative-state' }, { state_root: join(context.copy, 'state') }, { cohort_kind: 'blind_confirmation' },
    { cohort_kind: 'independent_live' }, { independent_live_accuracy: true }, { concurrency: 2 },
    { selection: { sample: 1 } }, { selection: { sample: 2, seed: 'x', limit: 2 } }, { max_cases: 3 },
    { total_timeout_ms: 900001 }, { selection: { limit: 0 } }, { baseline: undefined },
  ]) assert.throws(() => freezePlan({ ...context.config, ...changes }));
  const wrong = read(context.baseline);
  wrong.provenance.register_sha256 = 'a'.repeat(64);
  writeFileSync(context.baseline, JSON.stringify(wrong));
  assert.throws(() => freezePlan(context.config), /INCOMPATIBLE_BASELINE/);
  assert.equal(existsSync(join(context.copy, 'state')), false);
});

test('private state rejects symlink components, noncanonical paths and writable ancestors before creating anything', (t) => {
  const context = fixture(t);
  const actual = join(context.scratch, 'actual');
  mkdirSync(actual, { mode: 0o700 });
  const alias = join(context.scratch, 'alias');
  symlinkSync(actual, alias, 'dir');
  assert.throws(() => freezePlan({ ...context.config, state_root: alias }), /SYMLINK_OR_NON_DIRECTORY/);
  assert.throws(() => freezePlan({ ...context.config, state_root: join(alias, 'new-root') }), /SYMLINK_OR_NON_DIRECTORY/);
  assert.equal(existsSync(join(actual, 'new-root')), false);
  assert.throws(() => freezePlan({ ...context.config, state_root: `${context.state_root}/../noncanonical` }), /CANONICAL_STATE_ROOT_REQUIRED/);
  const loose = join(context.scratch, 'loose');
  mkdirSync(loose, { mode: 0o700 });
  chmodSync(loose, 0o777);
  assert.throws(() => freezePlan({ ...context.config, state_root: join(loose, 'new-root') }), /UNTRUSTED_STATE_ANCESTOR/);
  assert.equal(existsSync(join(loose, 'new-root')), false);
});

test('a selected sample must have a matching baseline and cannot become confirmation', async (t) => {
  const context = fixture(t);
  assert.throws(() => freezePlan({ ...context.config, selection: { sample: 2, seed: 'stable' } }), /INCOMPATIBLE_BASELINE/);
  const baseline = context.generateBaseline(['--sample', '2', '--seed', 'stable'], join(context.scratch, 'sample-baseline.md'));
  const frozen = freezePlan({ ...context.config, baseline, selection: { sample: 2, seed: 'stable' } });
  const result = await runPlan(request(context, frozen));
  assert.equal(result.aggregate.all_case_denominator, 2);
  assert.equal(result.aggregate.blind_confirmation, false);
  assert.equal(result.readiness.goal_over_90_percent, 'UNMET');
});

test('changed register, workflow source and canonical skill content invalidate the old job', async (t) => {
  const context = fixture(t);
  const original = freezePlan(context.config);
  appendFileSync(join(context.copy, 'estimator/src/price.ts'), '\n');
  const failed = await runPlan(request(context, original));
  assert.equal(failed.state, 'FAILED');
  assert.equal(failed.failure.code, 'SOURCE_OR_RUNTIME_HASH_CHANGED');
  assert.equal(existsSync(join(jobDirectory(context, original), 'candidate.json')), false);
  const sourceChanged = freezePlan(context.config);
  assert.notEqual(sourceChanged.job_key, original.job_key);
  appendFileSync(join(context.copy, '.agents/skills/keller-estimator-evals/SKILL.md'), '\nAdditional operator context.\n');
  assert.equal(statusPlan(request(context, sourceChanged)).state, 'INVALIDATED');
  const skillChanged = freezePlan(context.config);
  assert.notEqual(skillChanged.job_key, sourceChanged.job_key);
  appendFileSync(context.register, 'C-old,,2023-01-01,CCCC,open,10,20\n');
  assert.equal(statusPlan(request(context, skillChanged)).code, 'INPUT_HASH_CHANGED');
  assert.throws(() => freezePlan(context.config), /INCOMPATIBLE_BASELINE/);
  const baseline = context.generateBaseline([], join(context.scratch, 'changed-baseline.md'));
  const inputsChanged = freezePlan({ ...context.config, baseline });
  assert.notEqual(inputsChanged.job_key, skillChanged.job_key);
});

test('the controller checks source hashes again immediately after the real runner', async (t) => {
  const context = fixture(t);
  appendFileSync(join(context.copy, 'evals/run-eval.ts'),
    '\nconst mutate = await import("node:fs"); mutate.appendFileSync(new URL("../estimator/src/price.ts", import.meta.url), "\\n");\n');
  const frozen = freezePlan(context.config);
  const result = await runPlan(request(context, frozen));
  assert.equal(result.state, 'FAILED');
  assert.equal(result.failure.code, 'SOURCE_OR_RUNTIME_HASH_CHANGED');
  const events = journal(jobDirectory(context, frozen));
  assert.equal(events.find((entry) => entry.event === 'command_completed').payload.source_verification_error, 'SOURCE_OR_RUNTIME_HASH_CHANGED');
  assert.ok(!events.some((entry) => entry.event === 'eval_completed'));
  assert.ok(existsSync(join(jobDirectory(context, frozen), 'candidate.json')));
});

test('checksum and plan tampering are rejected without overwriting success', async (t) => {
  const context = fixture(t);
  const frozen = freezePlan(context.config);
  assert.equal((await runPlan(request(context, frozen))).state, 'COMPLETED');
  const directory = jobDirectory(context, frozen);
  const success = journal(directory).find((entry) => entry.event === 'completed');
  appendFileSync(join(directory, 'candidate.json'), '\n');
  const retry = await runPlan(request(context, frozen));
  assert.equal(retry.state, 'FAILED');
  assert.equal(retry.failure.code, 'ARTIFACT_CHECKSUM_MISMATCH');
  assert.deepEqual(journal(directory).find((entry) => entry.event === 'completed'), success);
  assert.equal(statusPlan(request(context, frozen)).state, 'INVALIDATED');
  const plan = read(frozen.plan_path);
  plan.identity.limits.max_cases = 249;
  writeFileSync(frozen.plan_path, JSON.stringify(plan));
  assert.throws(() => statusPlan(request(context, frozen)), /PLAN_CHECKSUM_MISMATCH/);
});

test('journal tampering and missing artifacts are invalid, while atomic pending files are never checkpoints', async (t) => {
  const context = fixture(t);
  const frozen = freezePlan(context.config);
  const directory = jobDirectory(context, frozen);
  const pending = join(directory, 'journal', 'not-a-checkpoint.pending');
  writeFileSync(pending, '{');
  assert.equal(statusPlan(request(context, frozen)).state, 'FROZEN');
  unlinkSync(pending);
  assert.equal((await runPlan(request(context, frozen))).state, 'COMPLETED');
  unlinkSync(join(directory, 'candidate.md'));
  assert.equal(statusPlan(request(context, frozen)).state, 'INVALIDATED');
  const first = join(directory, 'journal', readdirSync(join(directory, 'journal')).sort()[0]);
  appendFileSync(first, '\n');
  assert.throws(() => statusPlan(request(context, frozen)), /JOURNAL_CHECKSUM_MISMATCH/);
  assert.ok(readdirSync(join(directory, 'incidents')).length >= 2);
});

test('concurrent invocations execute only one pricing run', async (t) => {
  const context = fixture(t);
  const frozen = freezePlan(context.config);
  const results = await Promise.all([runPlan(request(context, frozen)), runPlan(request(context, frozen))]);
  assert.deepEqual(results.map((result) => result.state).sort(), ['BUSY', 'COMPLETED']);
  const events = journal(jobDirectory(context, frozen));
  assert.equal(events.filter((entry) => entry.event === 'command_started' && entry.payload.stage === 'eval').length, 1);
});

test('locks are reclaimed only for proven-dead same-host owners, never by age', async (t) => {
  const context = fixture(t);
  const frozen = freezePlan(context.config);
  const path = join(context.state_root, 'execution.lock');
  for (const owner of [
    { host: hostname(), pid: process.pid, token: 'alive', started: 0 },
    { host: 'foreign-host', pid: 2147483647, token: 'foreign', started: 0 },
    { host: hostname(), pid: 2147483647, started: 0 },
    { host: hostname(), pid: 2147483647, token: '../bad-token', started: 0 },
  ]) {
    const bytes = JSON.stringify(owner);
    writeFileSync(path, bytes);
    assert.equal((await runPlan(request(context, frozen))).state, 'BUSY');
    assert.equal(readFileSync(path, 'utf8'), bytes);
  }
  writeFileSync(path, JSON.stringify({ host: hostname(), pid: 2147483647, token: 'dead', job_key: null }));
  assert.equal((await runPlan(request(context, frozen))).state, 'COMPLETED');
  assert.equal(existsSync(path), false);
  assert.equal(readdirSync(join(context.state_root, 'retired-locks')).length, 1);
});

test('a comparison-stage failure resumes verified eval artifacts but preserves the failed attempt', async (t) => {
  const context = fixture(t);
  const path = join(context.copy, 'evals/compare.ts');
  const original = readFileSync(path, 'utf8');
  writeFileSync(path, 'if (process.argv.some((arg) => arg.endsWith("comparison-1.md"))) throw new Error("fixture interruption");\n' + original);
  const frozen = freezePlan(context.config);
  const first = await runPlan(request(context, frozen));
  const directory = jobDirectory(context, frozen);
  assert.equal(first.state, 'FAILED');
  assert.equal(first.failure.code, 'COMPARISON_COMMAND_FAILED');
  const candidateHash = sha(readFileSync(join(directory, 'candidate.json')));
  const failureLog = readFileSync(join(directory, 'comparison-1.stderr'), 'utf8');
  assert.equal((await runPlan(request(context, frozen))).resume_required, true);
  const resumed = await runPlan(request(context, frozen, { resume: true }));
  assert.equal(resumed.state, 'COMPLETED_WITH_FAILURE_HISTORY');
  assert.equal(resumed.readiness.failure_history_count, 1);
  assert.equal(resumed.readiness.pipeline_verification, 'VERIFIED');
  assert.equal(sha(readFileSync(join(directory, 'candidate.json'))), candidateHash);
  assert.equal(readFileSync(join(directory, 'comparison-1.stderr'), 'utf8'), failureLog);
  const events = journal(directory);
  assert.equal(events.filter((entry) => entry.event === 'command_started' && entry.payload.stage === 'eval').length, 1);
  assert.equal(events.filter((entry) => entry.event === 'command_started' && entry.payload.stage === 'comparison').length, 2);
  assert.equal(events.filter((entry) => entry.event === 'failed').length, 1);
});

test('explicit comparison recovery cannot exceed its frozen attempts or total budget', async (t) => {
  const context = fixture(t, { max_attempts: 1 });
  const path = join(context.copy, 'evals/compare.ts');
  writeFileSync(path, 'throw new Error("fixture failure");\n' + readFileSync(path, 'utf8'));
  const frozen = freezePlan(context.config);
  assert.equal((await runPlan(request(context, frozen))).failure.code, 'COMPARISON_COMMAND_FAILED');
  const exhausted = await runPlan(request(context, frozen, { resume: true }));
  assert.equal(exhausted.failure.code, 'COMPARISON_ATTEMPTS_EXHAUSTED');
  assert.equal(journal(jobDirectory(context, frozen)).filter((entry) => entry.event === 'command_started').length, 2);
  const budget = freezePlan({ ...context.config, total_timeout_ms: 1 });
  assert.equal((await runPlan(request(context, budget))).failure.code, 'TOTAL_TIMEOUT_BUDGET_EXHAUSTED');
  assert.equal(journal(jobDirectory(context, budget)).filter((entry) => entry.event === 'command_started').length, 0);
});

test('real compare.ts rejects a regression without loosening the gate', async (t) => {
  const context = fixture(t);
  const path = join(context.copy, 'estimator/src/price.ts');
  const source = readFileSync(path, 'utf8');
  assert.ok(source.includes('return { unit_price: unit,'));
  writeFileSync(path, source.replace('return { unit_price: unit,', 'return { unit_price: unit === null ? null : unit * 3,'));
  const frozen = freezePlan(context.config);
  const result = await runPlan(request(context, frozen));
  assert.equal(result.state, 'REGRESSION');
  assert.equal(result.readiness.pipeline_verification, 'VERIFIED');
  assert.equal(result.readiness.diagnostic_regression, 'REGRESSION');
  assert.ok(result.aggregate.criterion_losses.unit_within_20pct > 0);
  const events = journal(jobDirectory(context, frozen));
  const command = events.find((entry) => entry.event === 'command_completed' && entry.payload.stage === 'comparison');
  assert.equal(command.payload.exit_code, 1);
  assert.equal(events.find((entry) => entry.event === 'comparison_completed').payload.outcome, 'REGRESSION');
  assert.equal((await runPlan(request(context, frozen))).verified_duplicate, true);
});

test('timeouts are hard-bounded and failed attempts are retained rather than rerun', async (t) => {
  const context = fixture(t, { command_timeout_ms: 50, total_timeout_ms: 3000 });
  appendFileSync(join(context.copy, 'evals/run-eval.ts'), '\nawait new Promise(() => {});\n');
  const frozen = freezePlan(context.config);
  const start = performance.now();
  const result = await runPlan(request(context, frozen));
  assert.equal(result.state, 'FAILED');
  assert.equal(result.failure.code, 'COMMAND_TIMEOUT');
  assert.ok(performance.now() - start < 5000);
  const directory = jobDirectory(context, frozen);
  const command = journal(directory).find((entry) => entry.event === 'command_completed');
  assert.equal(command.payload.timed_out, true);
  assert.equal(command.payload.signal, 'SIGKILL');
  assert.equal((await runPlan(request(context, frozen))).resume_required, true);
  const resumed = await runPlan(request(context, frozen, { resume: true }));
  assert.equal(resumed.failure.code, 'FAILED_EVAL_REQUIRES_NEW_PLAN');
  assert.equal(journal(directory).filter((entry) => entry.event === 'command_started').length, 1);
});

test('forced offline child environment discards gateway, database, and inherited Node options', async (t) => {
  const context = fixture(t);
  const path = join(context.copy, 'evals/run-eval.ts');
  writeFileSync(path, 'if (["AI_GATEWAY_API_KEY", "JEV_API_KEY", "POLYGRES_DATABASE_URL", "POLYGRES_DIRECT_URL", "PGPASSWORD", "NODE_OPTIONS"].some((name) => process.env[name]) || process.env.OFFLINE !== "1") throw new Error("inherited credentials");\n' + readFileSync(path, 'utf8'));
  const names = ['AI_GATEWAY_API_KEY', 'JEV_API_KEY', 'POLYGRES_DATABASE_URL', 'POLYGRES_DIRECT_URL', 'PGPASSWORD', 'NODE_OPTIONS'];
  const prior = Object.fromEntries(names.map((name) => [name, process.env[name]]));
  for (const name of names) process.env[name] = 'test-placeholder-not-a-secret';
  try {
    const frozen = freezePlan(context.config);
    assert.equal((await runPlan(request(context, frozen))).state, 'COMPLETED');
  } finally {
    for (const name of names) if (prior[name] === undefined) delete process.env[name]; else process.env[name] = prior[name];
  }
});

test('diagnosis includes missing failures, paired variance, every criterion loss, and no invented geometry cause', () => {
  const provenance = { register_sha256: 'a'.repeat(64), evalset_sha256: 'b'.repeat(64), selected_case_ids_sha256: 'c'.repeat(64), configuration: {} };
  const row = (id, predicted, failed = []) => ({ id, actual: 10, predicted, quantity: 2, source_quote_no: 'q', quote_date: '2024-01-01',
    status: predicted === null ? 'no_analog' : 'priced', actual_extended: 20, predicted_extended: predicted === null ? null : predicted * 2,
    criteria: Object.fromEntries(criteria.map((key) => [key, { pass: !failed.includes(key), reason: `${key} observed` }])) });
  const baseline = { schema_version: 2, provenance, results: [row('one', 10), row('two', 12), row('missing', 10)] };
  const report = { schema_version: 2, provenance, results: [row('one', 8, ['source_excluded']), row('two', 16, ['unit_within_20pct'])] };
  const diagnosis = diagnoseReport(report, { baseline });
  assert.equal(diagnosis.aggregate.all_case_denominator, 3);
  assert.deepEqual([diagnosis.aggregate.priced, diagnosis.aggregate.held, diagnosis.aggregate.error, diagnosis.aggregate.missing], [2, 0, 1, 1]);
  assert.equal(diagnosis.aggregate.criterion_losses.source_excluded, 2);
  assert.equal(diagnosis.aggregate.criterion_loss_count, 7);
  assert.equal(diagnosis.private_numeric_summary.signed_unit_error.mean, 2);
  assert.equal(diagnosis.private_numeric_summary.signed_unit_error.variance, 32);
  assert.equal(diagnosis.private_numeric_summary.paired_signed_unit_change.mean, 1);
  assert.equal(diagnosis.private_numeric_summary.paired_signed_unit_change.variance, 18);
  assert.equal(diagnosis.aggregate.paired_price_denominator, 2);
  assert.equal(diagnosis.work_items[0].category, 'source_eligibility');
  assert.ok(!JSON.stringify(diagnosis).includes('geometry'));
  const empty = diagnoseReport({ schema_version: 2, results: [] }, { expected_cases: ['missing'] });
  assert.equal(empty.aggregate.error, 1);
  assert.equal(empty.aggregate.priced_error_denominator, 0);
  assert.equal(empty.aggregate.signed_relative_error.mean, null);
  assert.equal(empty.aggregate.signed_relative_error.stddev, null);
  assert.equal(empty.private_numeric_summary.signed_unit_error.variance, null);
  assert.throws(() => diagnoseReport({ schema_version: 2, summary: baseline }), /SCHEMA_V2_RESULTS_REQUIRED/);
});

test('work queue is deterministic, dependency-bound and stops on missing inputs, reused sets, or attempt exhaustion', () => {
  const report = { schema_version: 2, provenance: { evalset_sha256: 'a'.repeat(64) }, results: [{ id: 'error', status: 'unreplayable', criteria: {} }] };
  const diagnosis = diagnoseReport(report);
  const schedule = buildSchedule(diagnosis);
  assert.deepEqual(buildSchedule(diagnosis), schedule);
  assert.equal(schedule.queue[0].type, 'diagnose');
  assert.ok(schedule.queue.length <= 10);
  assert.equal(schedule.concurrency, 1);
  assert.equal(schedule.state, 'BLOCKED');
  assert.deepEqual(schedule.queue.slice(-3).map((item) => item.type), ['matched_development', 'untouched_confirmation_request', 'independent_review']);
  const ready = buildSchedule(diagnosis, { evidence_ready: true, development_ready: true, confirmation_available: true,
    reviewer_available: true, history: [{ id: schedule.queue[0].id, status: 'completed', attempts: 1 }] });
  assert.equal(ready.queue[1].status, 'READY');
  const exhausted = buildSchedule(diagnosis, { history: [{ id: schedule.queue[0].id, status: 'failed', attempts: 1 }] });
  assert.equal(exhausted.queue[0].status, 'ESCALATE');
  const reused = buildSchedule(diagnosis, { confirmation_available: true, confirmation_evalset_sha256: 'a'.repeat(64) });
  assert.ok(reused.stop_reasons.some((item) => item.reason === 'USED_SET_CANNOT_CONFIRM'));
  assert.equal(reused.goal_over_90_percent, 'UNMET');
  assert.equal(reused.queue.find((item) => item.type === 'untouched_confirmation_request').external_only, true);
});

test('CLI accepts explicit configuration and JSON stdin, and returns only safe JSON', async (t) => {
  const context = fixture(t);
  const config = join(context.scratch, 'config.json');
  writeFileSync(config, JSON.stringify(context.config));
  const freeze = spawnSync(process.execPath, [controller, 'freeze', '--config', config], { cwd: repo, encoding: 'utf8' });
  assert.equal(freeze.status, 0, freeze.stdout);
  const frozen = JSON.parse(freeze.stdout);
  const run = spawnSync(process.execPath, [controller, 'run'], { cwd: repo, input: JSON.stringify(request(context, frozen)), encoding: 'utf8', timeout: 30000 });
  assert.equal(run.status, 0, run.stdout);
  assert.equal(JSON.parse(run.stdout).readiness.goal_over_90_percent, 'UNMET');
  assert.ok(!run.stdout.includes('Customer-private'));
  const diagnosis = spawnSync(process.execPath, [controller, 'diagnose'], { cwd: repo, input: JSON.stringify({ state_root: context.state_root,
    report: join(jobDirectory(context, frozen), 'candidate.json'), baseline: context.baseline }), encoding: 'utf8' });
  assert.equal(diagnosis.status, 0, diagnosis.stdout);
  assert.equal(JSON.parse(diagnosis.stdout).state, 'DIAGNOSED');
  assert.ok(!diagnosis.stdout.includes('Customer-private'));
});
