#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { closeSync, existsSync, fsyncSync, linkSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { hostname } from 'node:os';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const criteria = ['priced_finite', 'source_excluded', 'cutoff_evidence', 'unit_within_20pct', 'extension_reconciles'];
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex');
const canonical = (value) => JSON.stringify(value, (_, v) => v && typeof v === 'object' && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]])) : v);
const digest = (value) => sha(canonical(value));
const json = (path) => JSON.parse(readFileSync(path, 'utf8'));
const inside = (root, path) => path === root || (!relative(root, path).startsWith('..') && !isAbsolute(relative(root, path)));
const fail = (code) => { throw Object.assign(new Error(code), { code }); };
const keys = (object, allowed) => {
  if (!object || typeof object !== 'object' || Array.isArray(object) || Object.keys(object).some((key) => !allowed.includes(key))) fail('INVALID_CONFIGURATION');
};
const integer = (value, min, max) => {
  if (!Number.isSafeInteger(value) || value < min || value > max) fail('INVALID_BUDGET');
  return value;
};
const fileHash = (path) => {
  if (!lstatSync(path).isFile()) fail('EXPECTED_REGULAR_FILE');
  return sha(readFileSync(path));
};
const absoluteFile = (path) => {
  if (typeof path !== 'string' || !isAbsolute(path)) fail('ABSOLUTE_INPUT_PATH_REQUIRED');
  fileHash(path);
  return realpathSync(path);
};
const privateRoot = (path, repo, create = false) => {
  if (typeof path !== 'string' || !isAbsolute(path)) fail('ABSOLUTE_PRIVATE_STATE_ROOT_REQUIRED');
  if (resolve(path) !== path) fail('CANONICAL_STATE_ROOT_REQUIRED');
  if (inside(repo, resolve(path)) || inside(resolve(path), repo) || inside(checkout, resolve(path)) || inside(resolve(path), checkout)) fail('STATE_ROOT_MUST_BE_OUTSIDE_CHECKOUT');
  const validateAncestors = () => {
    let current = '/';
    for (const component of ['', ...path.split('/').filter(Boolean)]) {
      current = join(current, component);
      let info;
      try { info = lstatSync(current); } catch (error) { if (error.code === 'ENOENT') break; throw error; }
      if (info.isSymbolicLink() || !info.isDirectory()) fail('SYMLINK_OR_NON_DIRECTORY_STATE_COMPONENT');
      if (![0, process.getuid?.()].includes(info.uid) || (info.mode & 0o022)) fail('UNTRUSTED_STATE_ANCESTOR');
    }
  };
  validateAncestors();
  if (create) mkdirSync(path, { recursive: true, mode: 0o700 });
  validateAncestors();
  const root = path;
  const info = lstatSync(root);
  if (!info.isDirectory() || (info.mode & 0o077) || info.uid !== process.getuid?.()) fail('OWNER_ONLY_STATE_ROOT_REQUIRED');
  if (inside(repo, root) || inside(root, repo) || inside(checkout, root) || inside(root, checkout)) fail('STATE_ROOT_MUST_BE_OUTSIDE_CHECKOUT');
  return root;
};
const immutable = (path, bytes) => {
  const temporary = `${path}.${randomUUID()}.pending`;
  const fd = openSync(temporary, 'wx', 0o600);
  try { writeFileSync(fd, bytes); fsyncSync(fd); }
  finally { closeSync(fd); }
  try { linkSync(temporary, path); }
  finally { unlinkSync(temporary); }
  const directory = openSync(dirname(path), 'r');
  try { fsyncSync(directory); } finally { closeSync(directory); }
};
const writeJson = (path, value) => immutable(path, `${JSON.stringify(value, null, 2)}\n`);
const files = (directory, accept) => readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).flatMap((entry) => {
  const path = join(directory, entry.name);
  if (entry.isSymbolicLink()) fail('SYMLINK_SOURCE_REFUSED');
  return entry.isDirectory() ? files(path, accept) : entry.isFile() && accept(path) ? [path] : [];
});
const sourceFiles = (repo) => [...new Set([...files(join(repo, 'estimator/src'), (path) => /\.(ts|mjs)$/.test(path)),
  ...files(join(repo, 'evals'), (path) => path.endsWith('.ts')),
  ...readdirSync(join(repo, 'scripts')).filter((name) => /\.(mjs|py|sh|ts)$/.test(name)).map((name) => join(repo, 'scripts', name)),
  ...['arsumbris', 'type', 'profiles', 'skills', 'inject', '.arsumbris'].flatMap((name) => existsSync(join(repo, name))
    ? files(join(repo, name), (path) => /\.(ts|mjs|py|json|yaml|yml|toml|md)$/.test(path)) : []),
  ...['estimator/package-lock.json', 'estimator/package.json', 'estimator/tsconfig.json', 'evals/package.json', 'evals/tsconfig.json',
    'scripts/keller-improvement.mjs', 'docs/decision-quality.md', 'docs/mcp-trajectory-analysis.md'].map((path) => join(repo, path))])].sort();
const skillFiles = (repo, extras) => [...new Set([...files(join(repo, '.agents/skills'), (path) => path.endsWith('/SKILL.md')), ...extras])].sort();
const records = (paths) => {
  if (paths.length > 1024) fail('SOURCE_INVENTORY_BUDGET_EXCEEDED');
  return paths.map((path) => ({ path, sha256: fileHash(path) }));
};
const artifacts = (directory, names) => names.filter((name) => existsSync(join(directory, name))).map((name) => ({ file: name, sha256: fileHash(join(directory, name)) }));
const verifyArtifacts = (directory, entries) => {
  for (const entry of entries) {
    try {
      const info = lstatSync(join(directory, entry.file));
      if (!entry || typeof entry.file !== 'string' || !inside(directory, resolve(directory, entry.file)) ||
        info.uid !== process.getuid?.() || (info.mode & 0o077) ||
        entry.sha256 !== fileHash(join(directory, entry.file))) fail('ARTIFACT_CHECKSUM_MISMATCH');
    } catch { fail('ARTIFACT_CHECKSUM_MISMATCH'); }
  }
};
const readJournal = (directory, key) => {
  let previous = null;
  return readdirSync(join(directory, 'journal')).filter((name) => !name.endsWith('.pending')).sort().map((name, index) => {
    const path = join(directory, 'journal', name);
    const bytes = readFileSync(path);
    const entry = JSON.parse(bytes);
    if (name !== `${String(index + 1).padStart(6, '0')}-${sha(bytes)}.json` || entry.seq !== index + 1 ||
      entry.job_key !== key || entry.previous_sha256 !== previous) fail('JOURNAL_CHECKSUM_MISMATCH');
    previous = sha(bytes);
    return { ...entry, sha256: previous };
  });
};
const append = (directory, key, event, payload = {}) => {
  const journal = readJournal(directory, key);
  const entry = { seq: journal.length + 1, job_key: key, previous_sha256: journal.at(-1)?.sha256 ?? null,
    event, at: new Date().toISOString(), payload };
  const bytes = `${JSON.stringify(entry, null, 2)}\n`;
  immutable(join(directory, 'journal', `${String(entry.seq).padStart(6, '0')}-${sha(bytes)}.json`), bytes);
  return entry;
};
const dead = (pid, group = false) => {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try { process.kill(group ? -pid : pid, 0); return false; }
  catch (error) { return error.code === 'ESRCH'; }
};
const reclaimable = (root, owner) => {
  if (owner.host !== hostname() || typeof owner.token !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(owner.token) || !dead(owner.pid)) return false;
  if (!owner.job_key) return true;
  try {
    const journal = readJournal(join(root, 'jobs', owner.job_key), owner.job_key);
    return journal.filter((entry) => entry.event === 'command_started' && entry.payload.lock_token === owner.token).every((entry) => {
      const id = entry.payload.command_id;
      if (journal.some((next) => next.event === 'command_completed' && next.payload.command_id === id)) return true;
      const child = journal.find((next) => next.event === 'command_spawned' && next.payload.command_id === id);
      return child?.payload.host === hostname() && dead(child.payload.pid) && dead(child.payload.pid, true);
    });
  } catch { return false; }
};
const lock = (root, job_key = null) => {
  const path = join(root, 'execution.lock');
  const owner = { host: hostname(), pid: process.pid, token: randomUUID(), job_key };
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const fd = openSync(path, 'wx', 0o600);
      try { writeFileSync(fd, JSON.stringify(owner)); fsyncSync(fd); } finally { closeSync(fd); }
      return owner;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const recovery = join(root, 'recovery.lock');
      let fd;
      try { fd = openSync(recovery, 'wx', 0o600); } catch (e) { if (e.code === 'EEXIST') return null; throw e; }
      try {
        closeSync(fd);
        if (!lstatSync(path).isFile()) return null;
        const current = json(path);
        if (!reclaimable(root, current)) return null;
        mkdirSync(join(root, 'retired-locks'), { recursive: true, mode: 0o700 });
        renameSync(path, join(root, 'retired-locks', `${current.token}-${owner.token}.json`));
      } catch { return null; }
      finally { unlinkSync(recovery); }
    }
  }
  return null;
};
const unlock = (root, owner) => {
  const path = join(root, 'execution.lock');
  if (existsSync(path) && json(path).token === owner.token) unlinkSync(path);
};
const effectiveConfiguration = (selection) => ({ mode: 'cutoff-aware', limit: selection.limit ?? null,
  sample: selection.sample ?? null, seed: selection.sample === undefined ? null : selection.seed,
  jev_requested: false, jev_configured: false, exclusion: 'source quote_no', cutoff: 'case quote_date exclusive' });
const selectedCases = (bytes, selection, cap) => {
  const all = bytes.toString('utf8').split('\n').filter((line) => line.trim()).map((line) => JSON.parse(line));
  if (all.some((item) => !item || typeof item.id !== 'string' || !item.id) || new Set(all.map((item) => item.id)).size !== all.length) fail('INVALID_CASE_IDENTITIES');
  const selected = selection.sample === undefined ? all.slice(0, selection.limit) : [...all].sort((a, b) =>
    sha(`${selection.seed}\n${a.id}`).localeCompare(sha(`${selection.seed}\n${b.id}`)) || a.id.localeCompare(b.id)).slice(0, selection.sample);
  if (selection.sample > all.length || !selected.length || selected.length > cap) fail('CASE_BUDGET_EXCEEDED');
  return selected;
};
const compatible = (baseline, hashes, configuration, selected) => {
  if (baseline.schema_version !== 2 || !Array.isArray(baseline.results) || !baseline.summary ||
    baseline.summary.cases !== selected.length || baseline.results.length !== selected.length ||
    baseline.provenance?.register_sha256 !== hashes.register || baseline.provenance.evalset_sha256 !== hashes.evalset ||
    canonical(baseline.provenance.configuration) !== canonical(configuration) ||
    baseline.provenance.selected_case_ids_sha256 !== sha(JSON.stringify(selected.map((item) => item.id))) ||
    new Set(baseline.results.map((item) => item.id)).size !== selected.length) fail('INCOMPATIBLE_BASELINE');
  const before = new Map(baseline.results.map((item) => [item.id, item]));
  for (const item of selected) {
    const prior = before.get(item.id);
    const source = typeof item.source_quote_no === 'string' && item.source_quote_no === item.source_quote_no.trim() ? item.source_quote_no : '';
    if (!prior || prior.actual !== (Number.isFinite(item.actual_unit_price) ? item.actual_unit_price : null) ||
      prior.quantity !== item.input?.quantity || prior.source_quote_no !== source || prior.quote_date !== item.quote_date) fail('INCOMPATIBLE_BASELINE_TARGET');
    const targetFields = ['target_price_basis', 'target_quote_letter', 'target_document', 'target_document_sha256',
      'target_transcript_sha256', 'target_source_field', 'target_printed_extension', 'target_unit_price'];
    const target = targetFields.some((key) => item[key] !== undefined) ? {
      price_basis: item.target_price_basis, quote_letter: item.target_quote_letter, source_document: item.target_document,
      source_document_sha256: item.target_document_sha256, source_transcript_sha256: item.target_transcript_sha256,
      source_price_field: item.target_source_field, printed_extension: item.target_printed_extension, unit_price: item.target_unit_price,
    } : null;
    if (canonical(prior.target ?? null) !== canonical(target)) fail('INCOMPATIBLE_BASELINE_TARGET');
  }
};

export function freezePlan(config) {
  keys(config, ['state_root', 'repo_root', 'register', 'evalset', 'baseline', 'cohort_kind', 'selection', 'max_cases',
    'command_timeout_ms', 'total_timeout_ms', 'max_attempts', 'skills', 'concurrency']);
  if ((config.cohort_kind ?? 'diagnostic') !== 'diagnostic') fail('ONLY_DIAGNOSTIC_COHORT_SUPPORTED');
  if (Number(process.versions.node.split('.')[0]) < 24) fail('NODE_24_REQUIRED');
  if ((config.concurrency ?? 1) !== 1) fail('CONCURRENCY_MUST_BE_ONE');
  const repo = realpathSync(config.repo_root ?? checkout);
  if (!isAbsolute(config.repo_root ?? checkout)) fail('ABSOLUTE_REPO_ROOT_REQUIRED');
  const root = privateRoot(config.state_root, repo, true);
  const selection = config.selection ?? {};
  keys(selection, ['limit', 'sample', 'seed']);
  if (selection.limit !== undefined) integer(selection.limit, 1, 250);
  if (selection.sample !== undefined) integer(selection.sample, 1, 250);
  if (selection.limit !== undefined && selection.sample !== undefined || selection.seed !== undefined && selection.sample === undefined ||
    selection.sample !== undefined && (typeof selection.seed !== 'string' || !selection.seed.trim())) fail('INVALID_SELECTION');
  if (config.skills !== undefined && !Array.isArray(config.skills)) fail('INVALID_SKILLS');
  const extras = (config.skills ?? []).map(absoluteFile);
  const inputs = Object.fromEntries(['register', 'evalset', 'baseline'].map((name) => {
    const path = absoluteFile(config[name]);
    return [name, { path, sha256: fileHash(path) }];
  }));
  const maxCases = integer(config.max_cases ?? 250, 1, 250);
  const selected = selectedCases(readFileSync(inputs.evalset.path), selection, maxCases);
  const configuration = effectiveConfiguration(selection);
  compatible(json(inputs.baseline.path), { register: inputs.register.sha256, evalset: inputs.evalset.sha256 }, configuration, selected);
  const identity = { version: 1, cohort_kind: 'diagnostic', repo_root: repo, inputs, selection, configuration,
    selected_case_ids_sha256: sha(JSON.stringify(selected.map((item) => item.id))), case_count: selected.length,
    limits: { max_cases: maxCases, concurrency: 1, command_timeout_ms: integer(config.command_timeout_ms ?? 120000, 1, 900000),
      total_timeout_ms: integer(config.total_timeout_ms ?? 300000, 1, 900000), max_attempts: integer(config.max_attempts ?? 2, 1, 3) },
    sources: records(sourceFiles(repo)), skills: records(skillFiles(repo, extras)), extra_skills: extras,
    runtime: { node: process.versions.node, executable: process.execPath, executable_sha256: sha(readFileSync(process.execPath)),
      controller: { path: fileURLToPath(import.meta.url), sha256: fileHash(fileURLToPath(import.meta.url)) },
      tsx: { path: join(repo, 'estimator/node_modules/tsx/dist/cli.mjs'), sha256: fileHash(join(repo, 'estimator/node_modules/tsx/dist/cli.mjs')) } } };
  const key = digest(identity);
  const owner = lock(root);
  if (!owner) return { state: 'BUSY', job_key: key };
  const directory = join(root, 'jobs', key);
  try {
    if (existsSync(directory)) {
      const loaded = loadPlan({ state_root: root, job_key: key });
      assertInputs(loaded.plan);
      verifyArtifacts(directory, loaded.journal.flatMap((entry) => entry.payload.artifacts ?? []));
      return { state: 'FROZEN', duplicate: true, job_key: key, plan_path: join(directory, 'plan.json') };
    }
    mkdirSync(join(root, 'jobs'), { recursive: true, mode: 0o700 });
    mkdirSync(directory, { mode: 0o700 });
    mkdirSync(join(directory, 'journal'), { mode: 0o700 });
    mkdirSync(join(directory, 'inputs'), { mode: 0o700 });
    for (const [name, input] of Object.entries(inputs)) {
      const bytes = readFileSync(input.path);
      if (sha(bytes) !== input.sha256) fail('INPUT_CHANGED_DURING_FREEZE');
      immutable(join(directory, 'inputs', name), bytes);
    }
    const plan = { schema_version: 1, job_key: key, state_root: root, frozen_at: new Date().toISOString(), identity };
    writeJson(join(directory, 'plan.json'), plan);
    append(directory, key, 'frozen', { plan_sha256: fileHash(join(directory, 'plan.json')),
      artifacts: artifacts(directory, ['inputs/register', 'inputs/evalset', 'inputs/baseline']) });
    assertInputs(plan);
    return { state: 'FROZEN', duplicate: false, job_key: key, plan_path: join(directory, 'plan.json') };
  } catch (error) {
    if (existsSync(directory)) incident(directory, key, error.code ?? 'FREEZE_FAILED');
    throw error;
  } finally { unlock(root, owner); }
}

const loadPlan = (request) => {
  keys(request, ['state_root', 'job_key', 'resume']);
  if (!/^[a-f0-9]{64}$/.test(request.job_key ?? '')) fail('INVALID_JOB_KEY');
  const root = privateRoot(request.state_root, checkout);
  const directory = join(root, 'jobs', request.job_key);
  if (realpathSync(directory) !== directory || realpathSync(join(directory, 'journal')) !== join(directory, 'journal')) fail('SYMLINK_STATE_REFUSED');
  try {
    const plan = json(join(directory, 'plan.json'));
    const journal = readJournal(directory, request.job_key);
    if (plan.schema_version !== 1 || plan.job_key !== request.job_key || digest(plan.identity) !== request.job_key ||
      plan.state_root !== root || journal[0]?.event !== 'frozen' ||
      journal[0].payload.plan_sha256 !== fileHash(join(directory, 'plan.json'))) fail('PLAN_CHECKSUM_MISMATCH');
    privateRoot(root, plan.identity.repo_root);
    return { root, directory, plan, journal };
  } catch (error) {
    incident(directory, request.job_key, error.code ?? 'INVALID_PLAN_OR_JOURNAL');
    throw error;
  }
};
const assertInputs = (plan) => {
  const id = plan.identity;
  for (const [name, input] of Object.entries(id.inputs)) {
    if (fileHash(input.path) !== input.sha256) fail('INPUT_HASH_CHANGED');
    if (fileHash(join(plan.state_root, 'jobs', plan.job_key, 'inputs', name)) !== input.sha256) fail('FROZEN_INPUT_HASH_CHANGED');
  }
  if (canonical(records(sourceFiles(id.repo_root))) !== canonical(id.sources) ||
    canonical(records(skillFiles(id.repo_root, id.extra_skills))) !== canonical(id.skills) ||
    process.versions.node !== id.runtime.node || process.execPath !== id.runtime.executable ||
    sha(readFileSync(process.execPath)) !== id.runtime.executable_sha256 ||
    id.runtime.controller.path !== fileURLToPath(import.meta.url) || fileHash(id.runtime.controller.path) !== id.runtime.controller.sha256 ||
    fileHash(id.runtime.tsx.path) !== id.runtime.tsx.sha256) fail('SOURCE_OR_RUNTIME_HASH_CHANGED');
};
const readiness = (pipeline = 'UNVERIFIED', regression = 'UNASSESSED', failures = 0) => ({
  pipeline_verification: pipeline, diagnostic_regression: regression, failure_history_count: failures,
  independent_live_accuracy: 'NOT_ESTABLISHED', goal_over_90_percent: 'UNMET', cohort_kind: 'diagnostic',
  blind_confirmation: false, customer_release: 'REQUIRES_HUMAN_REVIEW',
});
const incident = (directory, key, code) => {
  mkdirSync(join(directory, 'incidents'), { recursive: true, mode: 0o700 });
  writeJson(join(directory, 'incidents', `${randomUUID()}.json`), { job_key: key, code, at: new Date().toISOString() });
};
const envOffline = (root) => ({ PATH: '/usr/bin:/bin', LANG: 'C.UTF-8', TZ: 'UTC', NODE_ENV: 'test',
  OFFLINE: '1', KELLER_OFFLINE: '1', TSX_DISABLE_CACHE: '1', HOME: root, TMPDIR: root });
const executeCommand = async (loaded, owner, stage, attempt, args, expectedFiles, remaining) => {
  const { directory, plan } = loaded;
  const key = plan.job_key;
  const id = `${stage}-${attempt}`;
  const out = `${id}.stdout`;
  const err = `${id}.stderr`;
  if (remaining <= 0) fail('TOTAL_TIMEOUT_BUDGET_EXHAUSTED');
  const timeout = Math.min(plan.identity.limits.command_timeout_ms, remaining);
  const started = performance.now();
  append(directory, key, 'command_started', { stage, attempt, command_id: id, args, timeout_ms: timeout, lock_token: owner.token });
  const stdout = openSync(join(directory, out), 'wx', 0o600);
  const stderr = openSync(join(directory, err), 'wx', 0o600);
  let result;
  let changed = null;
  try {
    assertInputs(plan);
    result = await new Promise((done, reject) => {
      let child;
      const mask = process.umask(0o077);
      try {
        child = spawn(process.execPath, [plan.identity.runtime.tsx.path, ...args], {
          cwd: plan.identity.repo_root, env: envOffline(loaded.root), stdio: ['ignore', stdout, stderr], detached: true,
        });
      } finally { process.umask(mask); }
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        try { process.kill(-child.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') reject(error); }
      }, timeout);
      child.once('spawn', () => {
        try { append(directory, key, 'command_spawned', { command_id: id, host: hostname(), pid: child.pid }); }
        catch (error) { process.kill(-child.pid, 'SIGKILL'); clearTimeout(timer); reject(error); }
      });
      child.once('error', (error) => { clearTimeout(timer); reject(error); });
      child.once('close', (exit_code, signal) => { clearTimeout(timer); done({ exit_code, signal, timed_out: timedOut }); });
    });
    try { assertInputs(plan); } catch (error) { changed = error.code ?? 'SOURCE_VERIFICATION_FAILED'; }
  } finally { closeSync(stdout); closeSync(stderr); }
  const payload = { stage, attempt, command_id: id, ...result, elapsed_ms: Math.ceil(performance.now() - started), source_verification_error: changed,
    artifacts: artifacts(directory, [out, err, ...expectedFiles]) };
  append(directory, key, 'command_completed', payload);
  if (changed) fail(changed);
  if (result.timed_out) fail('COMMAND_TIMEOUT');
  return payload;
};
const latest = (journal, event) => journal.findLast((entry) => entry.event === event);
const runnerSourceHash = (plan, report) => {
  if (!Array.isArray(report.provenance?.hashed_files)) fail('MISSING_RUNNER_SOURCE_BINDING');
  const hash = createHash('sha256');
  for (const file of report.provenance.hashed_files) {
    if (!plan.identity.sources.some((entry) => entry.path === join(plan.identity.repo_root, file))) fail('UNFROZEN_RUNNER_SOURCE');
    hash.update(file).update('\0').update(readFileSync(join(plan.identity.repo_root, file))).update('\0');
  }
  return hash.digest('hex');
};

export async function runPlan(request) {
  const loaded = loadPlan(request);
  const { root, directory, plan } = loaded;
  const key = plan.job_key;
  const owner = lock(root, key);
  if (!owner) return { state: 'BUSY', job_key: key, readiness: readiness() };
  let stage = 'verification';
  let attempt = 0;
  const start = performance.now();
  try {
    assertInputs(plan);
    verifyArtifacts(directory, loaded.journal.flatMap((entry) => entry.payload.artifacts ?? []));
    const finished = latest(loaded.journal, 'completed');
    const failures = loaded.journal.filter((entry) => entry.event === 'failed');
    if (finished) return { ...finished.payload.result, duplicate: true, verified_duplicate: true };
    if (failures.length && request.resume !== true) return { state: 'FAILED', job_key: key, resume_required: true,
      failure: failures.at(-1).payload, readiness: readiness('UNVERIFIED', 'UNASSESSED', failures.length) };
    const unfinished = loaded.journal.filter((entry) => entry.event === 'command_started').find((entry) =>
      !loaded.journal.some((next) => next.event === 'command_completed' && next.payload.command_id === entry.payload.command_id));
    if (unfinished) fail('AMBIGUOUS_INTERRUPTED_COMMAND_REQUIRES_REVIEW');
    const spent = loaded.journal.filter((entry) => entry.event === 'command_started').reduce((sum, entry) => {
      const completion = loaded.journal.find((next) => next.event === 'command_completed' && next.payload.command_id === entry.payload.command_id);
      return sum + (completion?.payload.elapsed_ms ?? entry.payload.timeout_ms);
    }, 0);
    const remaining = () => Math.floor(plan.identity.limits.total_timeout_ms - spent - (performance.now() - start));
    stage = 'eval';
    let evalComplete = latest(loaded.journal, 'eval_completed');
    if (!evalComplete) {
      if (loaded.journal.some((entry) => entry.event === 'command_started' && entry.payload.stage === 'eval')) fail('FAILED_EVAL_REQUIRES_NEW_PLAN');
      attempt = 1;
      const args = [join(plan.identity.repo_root, 'evals/run-eval.ts'), join(directory, 'inputs/evalset'),
        '--register', join(directory, 'inputs/register'), '--report', join(directory, 'candidate.md')];
      if (plan.identity.selection.limit !== undefined) args.push('--limit', String(plan.identity.selection.limit));
      if (plan.identity.selection.sample !== undefined) args.push('--sample', String(plan.identity.selection.sample), '--seed', plan.identity.selection.seed);
      const command = await executeCommand(loaded, owner, stage, attempt, args, ['candidate.md', 'candidate.json'], remaining());
      if (command.exit_code !== 0) fail('EVAL_COMMAND_FAILED');
      const report = json(join(directory, 'candidate.json'));
      const selected = selectedCases(readFileSync(join(directory, 'inputs/evalset')), plan.identity.selection, plan.identity.limits.max_cases);
      compatible(report, { register: plan.identity.inputs.register.sha256, evalset: plan.identity.inputs.evalset.sha256 }, plan.identity.configuration, selected);
      if (runnerSourceHash(plan, report) !== report.provenance.estimator_eval_source_lock_sha256) fail('RUNNER_SOURCE_BINDING_MISMATCH');
      evalComplete = append(directory, key, 'eval_completed', { artifacts: artifacts(directory, ['candidate.md', 'candidate.json']) });
    }
    stage = 'comparison';
    let comparison = latest(readJournal(directory, key), 'comparison_completed');
    if (!comparison) {
      attempt = loaded.journal.filter((entry) => entry.event === 'command_started' && entry.payload.stage === 'comparison').length + 1;
      if (attempt > plan.identity.limits.max_attempts) fail('COMPARISON_ATTEMPTS_EXHAUSTED');
      const output = `comparison-${attempt}.md`;
      const args = [join(plan.identity.repo_root, 'evals/compare.ts'), join(directory, 'inputs/baseline'),
        join(directory, 'candidate.json'), '--report', join(directory, output), '--fail-on-regression'];
      const command = await executeCommand(loaded, owner, stage, attempt, args, [output], remaining());
      const regression = command.exit_code === 1 && existsSync(join(directory, output)) &&
        readFileSync(join(directory, `comparison-${attempt}.stderr`), 'utf8').includes('diagnostic regression: coverage loss, median APE increase, or all-pass loss');
      if (command.exit_code !== 0 && !regression || !existsSync(join(directory, output))) fail('COMPARISON_COMMAND_FAILED');
      if (regression) append(directory, key, 'failed', { stage, attempt, code: 'DIAGNOSTIC_REGRESSION' });
      comparison = append(directory, key, 'comparison_completed', { outcome: regression ? 'REGRESSION' : 'PASS',
        artifacts: artifacts(directory, [output]) });
    }
    stage = 'diagnosis';
    let diagnosed = latest(readJournal(directory, key), 'diagnosis_completed');
    if (!diagnosed) {
      const diagnosis = diagnoseReport(json(join(directory, 'candidate.json')), { baseline: json(join(directory, 'inputs/baseline')),
        expected_cases: selectedCases(readFileSync(join(directory, 'inputs/evalset')), plan.identity.selection, plan.identity.limits.max_cases) });
      writeJson(join(directory, 'diagnostics.private.json'), diagnosis);
      writeJson(join(directory, 'aggregate.json'), diagnosis.aggregate);
      writeJson(join(directory, 'schedule.json'), buildSchedule(diagnosis));
      diagnosed = append(directory, key, 'diagnosis_completed', { artifacts: artifacts(directory,
        ['diagnostics.private.json', 'aggregate.json', 'schedule.json']) });
    }
    stage = 'verification';
    assertInputs(plan);
    const journal = readJournal(directory, key);
    verifyArtifacts(directory, journal.flatMap((entry) => entry.payload.artifacts ?? []));
    const aggregate = json(join(directory, 'aggregate.json'));
    const failureCount = journal.filter((entry) => entry.event === 'failed').length;
    const regressed = comparison.payload.outcome === 'REGRESSION' || aggregate.criterion_loss_count > 0;
    const result = { state: regressed ? 'REGRESSION' : failureCount ? 'COMPLETED_WITH_FAILURE_HISTORY' : 'COMPLETED',
      job_key: key, duplicate: false, aggregate, readiness: readiness('VERIFIED', regressed ? 'REGRESSION' : 'NO_REGRESSION_OBSERVED', failureCount),
      artifacts: { aggregate: join(directory, 'aggregate.json'), diagnostics: join(directory, 'diagnostics.private.json'), schedule: join(directory, 'schedule.json') } };
    append(directory, key, 'completed', { result });
    return result;
  } catch (error) {
    const code = error.code && typeof error.code === 'string' ? error.code : 'CONTROLLER_STAGE_FAILED';
    try { append(directory, key, 'failed', { stage, attempt, code, artifacts: artifacts(directory,
      ['candidate.md', 'candidate.json', 'diagnostics.private.json', 'aggregate.json', 'schedule.json']) }); }
    catch { incident(directory, key, code); }
    return { state: 'FAILED', job_key: key, failure: { stage, attempt, code },
      readiness: readiness('UNVERIFIED', 'UNASSESSED', loaded.journal.filter((entry) => entry.event === 'failed').length + 1) };
  } finally { unlock(root, owner); }
}

export function statusPlan(request) {
  const loaded = loadPlan(request);
  try {
    assertInputs(loaded.plan);
    verifyArtifacts(loaded.directory, loaded.journal.flatMap((entry) => entry.payload.artifacts ?? []));
  } catch (error) {
    incident(loaded.directory, request.job_key, error.code ?? 'VERIFICATION_FAILED');
    return { state: 'INVALIDATED', job_key: request.job_key, readiness: readiness(), code: error.code ?? 'VERIFICATION_FAILED' };
  }
  const finished = latest(loaded.journal, 'completed');
  if (finished) return { ...finished.payload.result, verified: true };
  const failed = latest(loaded.journal, 'failed');
  return { state: failed ? 'FAILED' : loaded.journal.length === 1 ? 'FROZEN' : 'INCOMPLETE', job_key: request.job_key,
    checkpoints: loaded.journal.map((entry) => ({ seq: entry.seq, event: entry.event })), readiness: readiness(), failure: failed?.payload ?? null };
}

const finite = (value) => typeof value === 'number' && Number.isFinite(value);
const stats = (values) => {
  const count = values.length;
  const mean = count ? values.reduce((sum, value) => sum + value, 0) / count : null;
  const variance = count > 1 ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (count - 1) : null;
  return { count, mean, variance, stddev: variance === null ? null : Math.sqrt(variance) };
};
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2 : null;
};

export function diagnoseReport(report, options = {}) {
  keys(options, ['baseline', 'expected_cases']);
  if (report?.schema_version !== 2 || !Array.isArray(report.results)) fail('SCHEMA_V2_RESULTS_REQUIRED');
  const baseline = options.baseline;
  if (baseline && (baseline.schema_version !== 2 || !Array.isArray(baseline.results) ||
    ['register_sha256', 'evalset_sha256', 'selected_case_ids_sha256'].some((key) =>
      !/^[a-f0-9]{64}$/.test(report.provenance?.[key] ?? '') || report.provenance?.[key] !== baseline.provenance?.[key]) ||
    canonical(report.provenance?.configuration) !== canonical(baseline.provenance?.configuration))) fail('INCOMPATIBLE_DIAGNOSTIC_BASELINE');
  const mapping = (rows) => {
    if (rows.some((row) => !row || typeof row.id !== 'string' || !row.id) || new Set(rows.map((row) => row.id)).size !== rows.length) fail('INVALID_DIAGNOSTIC_IDENTITIES');
    return new Map(rows.map((row) => [row.id, row]));
  };
  const after = mapping(report.results);
  const before = mapping(baseline?.results ?? []);
  const expected = options.expected_cases?.map((item) => typeof item === 'string' ? { id: item } : item);
  const ids = expected ? [...mapping(expected).keys()] : [...new Set([...before.keys(), ...after.keys()])];
  if ([...after.keys(), ...before.keys()].some((id) => !ids.includes(id))) fail('UNEXPECTED_DIAGNOSTIC_CASE');
  const groupCriteria = { source_eligibility: ['source_excluded', 'cutoff_evidence'], input_or_execution: ['priced_finite'],
    source_availability: ['priced_finite'], arithmetic: ['extension_reconciles'], numeric_miss: ['unit_within_20pct'] };
  const privateCases = ids.map((id) => {
    const row = after.get(id);
    const prior = before.get(id);
    if (row && prior && ['actual', 'quantity', 'source_quote_no', 'quote_date'].some((key) => row[key] !== prior[key]) ||
      row && prior && canonical(row.target ?? null) !== canonical(prior.target ?? null)) fail('INCOMPATIBLE_DIAGNOSTIC_TARGET');
    const priced = row?.status === 'priced' && finite(row.predicted) && row.predicted > 0 && finite(row.actual) && row.actual > 0;
    const status = priced ? 'priced' : row?.status === 'no_analog' ? 'held' : 'error';
    const failedCriteria = criteria.filter((key) => row?.criteria?.[key]?.pass !== true);
    const losses = criteria.filter((key) => prior?.criteria?.[key]?.pass === true && row?.criteria?.[key]?.pass !== true);
    const gains = criteria.filter((key) => prior?.criteria?.[key]?.pass === false && row?.criteria?.[key]?.pass === true);
    const signed = priced ? row.predicted - row.actual : null;
    const priorPriced = prior?.status === 'priced' && finite(prior.predicted) && finite(prior.actual) && prior.actual > 0;
    const priorSigned = priorPriced ? prior.predicted - prior.actual : null;
    return { id, status, missing: !row, all_pass: priced && failedCriteria.length === 0, failed_criteria: failedCriteria,
      criterion_losses: losses, criterion_gains: gains, criteria: Object.fromEntries(criteria.map((key) => [key, {
        pass: row?.criteria?.[key]?.pass === true, reason: row?.criteria?.[key]?.reason ?? 'missing case or criterion evidence',
        baseline_pass: prior?.criteria?.[key]?.pass ?? null, baseline_reason: prior?.criteria?.[key]?.reason ?? null } ])),
      actual: row?.actual ?? null, predicted: priced ? row.predicted : null, signed_unit_error: signed,
      absolute_unit_error: signed === null ? null : Math.abs(signed), signed_relative_error: signed === null ? null : signed / row.actual,
      ape: signed === null ? null : Math.abs(signed) / row.actual,
      signed_extended_error: priced && finite(row.actual_extended) && finite(row.predicted_extended) ? row.predicted_extended - row.actual_extended : null,
      paired_baseline: priorPriced && priced,
      baseline_signed_unit_error: priorSigned,
      paired_signed_unit_change: priorPriced && priced ? signed - priorSigned : null,
      paired_signed_relative_change: priorPriced && priced ? (signed - priorSigned) / row.actual : null,
      paired_ape_change: priorPriced && priced ? (Math.abs(signed) - Math.abs(priorSigned)) / row.actual : null,
      categories: Object.keys(groupCriteria).filter((category) => category === 'source_availability' ? status === 'held' :
        category === 'input_or_execution' ? status === 'error' :
          (category === 'arithmetic' || category === 'numeric_miss') && !priced ? false :
            groupCriteria[category].some((key) => failedCriteria.includes(key))) };
  });
  const criterionCounts = (field) => Object.fromEntries(criteria.map((key) => [key, privateCases.filter((row) => row[field].includes(key)).length]));
  const priced = privateCases.filter((row) => row.status === 'priced');
  const pairs = privateCases.filter((row) => row.paired_baseline);
  const fingerprint = digest({ provenance: report.provenance && Object.fromEntries(Object.entries(report.provenance).filter(([key]) => key !== 'run_at')),
    results: report.results, expected: ids, baseline: baseline?.results ?? null });
  const workItems = Object.entries(groupCriteria).map(([category, observedCriteria], priority) => {
    const rows = privateCases.filter((row) => row.categories.includes(category));
    const losses = rows.reduce((sum, row) => sum + row.criterion_losses.filter((key) => observedCriteria.includes(key)).length, 0);
    return { id: digest({ fingerprint, category, ids: rows.map((row) => row.id) }), category, priority: priority + 1,
      affected_cases: rows.length, criterion_losses: losses, observed_failed_criteria: observedCriteria.filter((key) => rows.some((row) => row.failed_criteria.includes(key))) };
  }).filter((item) => item.affected_cases).sort((a, b) => b.criterion_losses - a.criterion_losses || a.priority - b.priority)
    .map((item, index) => ({ ...item, priority: index + 1 }));
  const count = privateCases.length;
  const aggregate = { schema_version: 1, diagnostic_fingerprint: fingerprint, cohort_kind: 'diagnostic', blind_confirmation: false,
    all_case_denominator: count, priced: priced.length, held: privateCases.filter((row) => row.status === 'held').length,
    error: privateCases.filter((row) => row.status === 'error').length, missing: privateCases.filter((row) => row.missing).length,
    all_pass_count: privateCases.filter((row) => row.all_pass).length,
    all_pass_rate: count ? privateCases.filter((row) => row.all_pass).length / count : null,
    priced_coverage: count ? priced.length / count : null, priced_error_denominator: priced.length,
    median_ape: median(priced.map((row) => row.ape)), absolute_relative_error: stats(priced.map((row) => row.ape)),
    signed_relative_error: stats(priced.map((row) => row.signed_relative_error)),
    within_20pct_priced_rate: priced.length ? priced.filter((row) => row.ape <= 0.2).length / priced.length : null,
    criteria: Object.fromEntries(criteria.map((key) => [key, { denominator: count, failed: criterionCounts('failed_criteria')[key],
      pass: count - criterionCounts('failed_criteria')[key] }])),
    matched_baseline: !!baseline, paired_price_denominator: pairs.length,
    criterion_losses: criterionCounts('criterion_losses'), criterion_gains: criterionCounts('criterion_gains'),
    criterion_loss_count: privateCases.reduce((sum, row) => sum + row.criterion_losses.length, 0),
    paired_signed_relative_change: stats(pairs.map((row) => row.paired_signed_relative_change)),
    paired_ape_change: stats(pairs.map((row) => row.paired_ape_change)), work_items: workItems,
    independent_live_accuracy: 'NOT_ESTABLISHED', goal_over_90_percent: 'UNMET',
    limitations: ['Final eval criteria are observed; MCP turns, manufacturing causes and original PDF authenticity are not attested.',
      'Fixed evalsets, diagnostic splits and previously exposed PDFs are never blind confirmation.'] };
  return { schema_version: 1, aggregate, private_cases: privateCases, work_items: workItems,
    used_evalset_sha256: report.provenance?.evalset_sha256 ?? null,
    private_numeric_summary: { signed_unit_error: stats(priced.map((row) => row.signed_unit_error)),
      absolute_unit_error: stats(priced.map((row) => row.absolute_unit_error)),
      paired_signed_unit_change: stats(pairs.map((row) => row.paired_signed_unit_change)) } };
}

export function buildSchedule(diagnosis, options = {}) {
  keys(options, ['history', 'evidence_ready', 'development_ready', 'confirmation_available', 'confirmation_evalset_sha256',
    'used_evalset_sha256', 'reviewer_available', 'max_attempts', 'max_items']);
  if (!diagnosis?.aggregate?.diagnostic_fingerprint || !Array.isArray(diagnosis.work_items)) fail('DIAGNOSIS_REQUIRED');
  const cap = integer(options.max_items ?? 10, 5, 10);
  const attempts = integer(options.max_attempts ?? 2, 1, 3);
  const history = options.history ?? [];
  if (options.used_evalset_sha256 !== undefined && !Array.isArray(options.used_evalset_sha256) ||
    ['evidence_ready', 'development_ready', 'confirmation_available', 'reviewer_available'].some((key) => options[key] !== undefined && typeof options[key] !== 'boolean')) fail('INVALID_SCHEDULE_INPUT');
  if (!Array.isArray(history) || new Set(history.map((item) => item.id)).size !== history.length ||
    history.some((item) => !['completed', 'failed', 'running'].includes(item.status) || !Number.isSafeInteger(item.attempts) || item.attempts < 0)) fail('INVALID_WORK_HISTORY');
  const queue = [];
  const add = (type, dependencies, available, details = {}, maxAttempts = attempts) => {
    const id = digest({ fingerprint: diagnosis.aggregate.diagnostic_fingerprint, type, details });
    const prior = history.find((item) => item.id === id);
    const used = prior?.attempts ?? 0;
    const status = prior?.status === 'completed' ? 'COMPLETE' : used >= maxAttempts ? 'ESCALATE' : prior?.status === 'running' ? 'RUNNING' :
      !available ? 'BLOCKED_MISSING_INPUT' : dependencies.some((key) => queue.find((item) => item.id === key)?.status !== 'COMPLETE') ? 'WAITING_DEPENDENCY' : 'READY';
    queue.push({ id, type, priority: queue.length + 1, dependencies, max_attempts: maxAttempts, attempts: used, status, ...details });
    return id;
  };
  const diagnosisId = add('diagnose', [], true, {}, 1);
  const remedies = diagnosis.work_items.slice(0, cap - 4).map((item) => add('evidence_remediation_or_skill_candidate', [diagnosisId],
    options.evidence_ready === true, { observed_work_item: item.id, category: item.category, observed_failed_criteria: item.observed_failed_criteria }));
  const deferred = diagnosis.work_items.length - remedies.length;
  const development = add('matched_development', remedies.length ? remedies : [diagnosisId], options.development_ready === true && deferred === 0,
    { unchanged_targets_and_compare_gate: true });
  const reused = options.confirmation_evalset_sha256 && [diagnosis.used_evalset_sha256, ...(options.used_evalset_sha256 ?? [])].includes(options.confirmation_evalset_sha256);
  const confirmation = add('untouched_confirmation_request', [development], options.confirmation_available === true && !reused,
    { external_only: true, requires_independent_live_evidence: true });
  add('independent_review', [confirmation], options.reviewer_available === true, { no_automatic_promotion: true }, 1);
  if (reused) queue.find((item) => item.id === confirmation).status = 'ESCALATE';
  const stops = queue.filter((item) => ['ESCALATE', 'BLOCKED_MISSING_INPUT'].includes(item.status)).map((item) => ({ work_item: item.id,
    reason: item.id === confirmation && reused ? 'USED_SET_CANNOT_CONFIRM' : item.status === 'ESCALATE' ? 'ATTEMPTS_EXHAUSTED' :
      item.id === development && deferred ? 'DEFERRED_DIAGNOSTIC_WORK_REQUIRES_REVIEW' : 'MISSING_REQUIRED_INPUT', type: item.type }));
  return { schema_version: 1, state: queue.some((item) => item.status === 'ESCALATE') ? 'ESCALATE' : stops.length ? 'BLOCKED' : 'READY',
    concurrency: 1, queue, stop_reasons: stops, deferred_work_items: deferred,
    independent_live_accuracy: 'NOT_ESTABLISHED', goal_over_90_percent: 'UNMET' };
}

const main = async () => {
  const [command, ...args] = process.argv.slice(2);
  if (!['freeze', 'run', 'status', 'diagnose'].includes(command) ||
    args.length && (args.length !== 2 || args[0] !== '--config' || !isAbsolute(args[1]))) fail('USAGE_FREEZE_RUN_STATUS_DIAGNOSE_JSON_STDIN_OR_ABSOLUTE_CONFIG');
  const config = args.length ? json(args[1]) : JSON.parse(readFileSync(0, 'utf8'));
  let result;
  if (command === 'freeze') result = freezePlan(config);
  else if (command === 'run') result = await runPlan(config);
  else if (command === 'status') result = statusPlan(config);
  else {
    keys(config, ['state_root', 'report', 'baseline', 'expected_cases', 'schedule']);
    const root = privateRoot(config.state_root, checkout, true);
    const report = json(absoluteFile(config.report));
    const baseline = config.baseline ? json(absoluteFile(config.baseline)) : undefined;
    const diagnosis = diagnoseReport(report, { baseline, expected_cases: config.expected_cases });
    const directory = join(root, `diagnosis-${diagnosis.aggregate.diagnostic_fingerprint}`);
    const bytes = `${JSON.stringify(diagnosis, null, 2)}\n`;
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, 'diagnostics.private.json');
    if (existsSync(path)) { if (fileHash(path) !== sha(bytes)) fail('DIAGNOSTIC_CHECKSUM_MISMATCH'); }
    else immutable(path, bytes);
    result = { state: 'DIAGNOSED', aggregate: diagnosis.aggregate, diagnostics_path: path,
      schedule: buildSchedule(diagnosis, config.schedule) };
  }
  console.log(JSON.stringify(result));
  if (['FAILED', 'INVALIDATED', 'REGRESSION', 'BUSY'].includes(result.state)) process.exitCode = result.state === 'BUSY' ? 3 : 1;
};

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.log(JSON.stringify({ state: 'FAILED', code: error.code && typeof error.code === 'string' ? error.code : 'INVALID_INPUT_OR_STATE', readiness: readiness() }));
    process.exitCode = 1;
  });
}
