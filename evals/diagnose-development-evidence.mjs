import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, statSync, realpathSync } from 'node:fs';
import { resolve, dirname, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';

process.umask(0o077);
const [baseline, caseFile, registerFile, reportFile, output] = process.argv.slice(2);
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const pins = {
  cases: '12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311',
  register: 'a7d84545b00ecb3f976d100d3e214885cca009189c1f59c500687539e5728757',
  retained_report: 'be2a5c691f632546d99534c0a9c08fb3c1e1e06012fc44ff4b126ed1c1436e0e',
};
const count = (rows, fn) => rows.filter(fn).length;
const tally = values => Object.fromEntries([...new Set(values)].sort().map(k => [k, count(values, x => x === k)]));
try {
  assert.equal(typeof process.getuid, 'function');
  assert.equal(isAbsolute(output), true);
  const parent = dirname(output);
  assert.equal(realpathSync(parent), parent);
  const permissions = statSync(parent);
  assert.equal(permissions.uid, process.getuid());
  assert.equal(permissions.mode & 0o077, 0);
  let insideGit = false;
  try { insideGit = execFileSync('git', ['rev-parse', '--is-inside-work-tree'], {cwd:parent, encoding:'utf8', stdio:['ignore','pipe','pipe']}).trim() === 'true'; } catch {}
  assert.equal(insideGit, false);
  assert.equal(execFileSync('git', ['rev-parse', 'HEAD'], {cwd: baseline, encoding:'utf8'}).trim(),
    '34a0880037cf1cd40ae062e68b7201ad0b8c4cd9');
  assert.equal(execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], {cwd: baseline, encoding:'utf8'}).trim(), '');
  assert.equal(sha(readFileSync(caseFile)), pins.cases);
  assert.equal(sha(readFileSync(registerFile)), pins.register);
  assert.equal(sha(readFileSync(reportFile)), pins.retained_report);
  const cases = readFileSync(caseFile, 'utf8').trim().split('\n').map(JSON.parse);
  const report = JSON.parse(readFileSync(reportFile, 'utf8'));
  assert.equal(report.provenance.evalset_sha256, pins.cases);
  assert.equal(report.provenance.register_sha256, pins.register);
  const source = createHash('sha256');
  for (const file of report.provenance.hashed_files) source.update(file + '\0').update(readFileSync(resolve(baseline, file))).update('\0');
  assert.equal(source.digest('hex'), report.provenance.estimator_eval_source_lock_sha256);
  assert.deepEqual(cases.map(c => c.id), report.results.map(r => r.id));
  assert.equal(cases.length, 250);
  assert.equal(new Set(cases.map(c => c.id)).size, 250);
  const {QuoteRegister, normalizePartNo} = await import(pathToFileURL(resolve(baseline, 'estimator/src/register.ts')));
  const {retrieve} = await import(pathToFileURL(resolve(baseline, 'estimator/src/retrieve.ts')));
  const reg = QuoteRegister.fromCsv(registerFile);
  const rows = [];
  for (let i = 0; i < cases.length; i++) {
    const result = report.results[i];
    if (result.slices.split !== 'development') continue;
    const c = cases[i];
    const part = {part_no:c.input.part_no, description:c.input.description, quantity:c.input.quantity};
    const candidates = retrieve(reg, part, {customerId:c.input.customer_id,
      exclude:new Set([c.source_quote_no]), asOf:c.quote_date, limit:reg.groups.length});
    const pn = normalizePartNo(part.part_no ?? '');
    const otherExact = pn ? reg.exactPart(part.part_no).filter(g => g.head.quote_no !== c.source_quote_no) : [];
    const exact = candidates.filter(a => pn && normalizePartNo(a.row.part_no) === pn);
    const priceable = a => a.breaks.some(b => Number.isFinite(b.quantity) && b.quantity > 0 && Number.isFinite(b.unit_price) && b.unit_price > 0);
    rows.push({case_id:c.id, status:result.status, all_pass:result.all_pass,
      failed_criteria:Object.entries(result.criteria).filter(([,v]) => !v.pass).map(([k])=>k),
      present_input_fields:Object.keys(c.input).filter(k => c.input[k] !== '' && c.input[k] !== null && c.input[k] !== undefined),
      exposed_analog_match:result.slices.analog_match,
      other_exact_groups:otherExact.length, eligible_exact_groups:exact.length,
      eligible_priceable_exact_groups:exact.filter(priceable).length,
      retrieved_candidates:candidates.length, top12_priceable:candidates.slice(0,12).filter(priceable).length,
      top3_pass_frozen_deterministic_screen:candidates.slice(0,3).filter(a=>a.score>=0.3).length,
      quantity_outside_all_top12_priceable_ranges:candidates.slice(0,12).filter(priceable).length > 0 &&
        candidates.slice(0,12).filter(priceable).every(a => {
          const qs = a.breaks.filter(b => Number.isFinite(b.quantity) && b.quantity > 0 && Number.isFinite(b.unit_price) && b.unit_price > 0).map(b=>b.quantity);
          return part.quantity < Math.min(...qs) || part.quantity > Math.max(...qs);
        })});
  }
  const fields = ['customer_id','part_no','description','quantity','material','finish','drawing_ref','revision','thickness','dimensions','tolerances','routing','cost_plus','should_cost'];
  const publicSummary = {
    schema_version:1, population:'development-only diagnostic of retained historical replay; not a new pricing evaluation',
    input_sha256:pins, retained_report_sha256:sha(readFileSync(reportFile)),
    script_sha256:sha(readFileSync(process.argv[1])), baseline_commit:'34a0880037cf1cd40ae062e68b7201ad0b8c4cd9',
    all_case_denominator:250, unchanged_retained_all_pass:report.summary.all_pass_count,
    inspected_development_cases:rows.length, other_cases_not_drilled_into:250-rows.length,
    development_statuses:tally(rows.map(r=>r.status)), development_all_pass:count(rows,r=>r.all_pass),
    development_failed_criteria:tally(rows.flatMap(r=>r.failed_criteria)),
    development_input_field_presence:Object.fromEntries(fields.map(f=>[f,count(rows,r=>r.present_input_fields.includes(f))])),
    development_exposed_analog_match:tally(rows.map(r=>r.exposed_analog_match)),
    development_exact_history:{no_same_part_outside_source:count(rows,r=>!r.other_exact_groups),
      same_part_outside_source_but_not_eligible:count(rows,r=>r.other_exact_groups>0 && !r.eligible_exact_groups),
      eligible_same_part:count(rows,r=>r.eligible_exact_groups>0), eligible_priceable_same_part:count(rows,r=>r.eligible_priceable_exact_groups>0)},
    development_retrieval:{zero_candidates:count(rows,r=>!r.retrieved_candidates),
      held_with_zero_candidates:count(rows,r=>r.status==='no_analog' && !r.retrieved_candidates),
      held_with_candidates:count(rows,r=>r.status==='no_analog' && r.retrieved_candidates>0),
      held_with_candidates_all_top3_quarantined:count(rows,r=>r.status==='no_analog' && r.retrieved_candidates>0 && !r.top3_pass_frozen_deterministic_screen),
      priced_with_top3_admission:count(rows,r=>r.status==='priced' && r.top3_pass_frozen_deterministic_screen>0),
      no_usable_price_in_top12:count(rows,r=>!r.top12_priceable),
      quantity_outside_all_top12_priceable_ranges:count(rows,r=>r.quantity_outside_all_top12_priceable_ranges)},
    scored_policy_change:false, new_pricing_execution:false, provider_requests:0,
    independent_manufacturing_judgments:null, current_cost_accuracy:null, realized_margin_accuracy:null,
  };
  writeFileSync(output, JSON.stringify({summary:publicSummary,cases:rows},null,2)+'\n', {mode:0o600,flag:'wx'});
  console.log(JSON.stringify(publicSummary,null,2));
} catch {
  console.error('DIAGNOSTIC_INPUT_OR_EXECUTION_FAILURE');
  process.exitCode=2;
}
