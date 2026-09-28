import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { QuoteRegister } from "../estimator/src/register.js";
import { estimate } from "../estimator/src/estimate.js";
import { JevClient } from "../estimator/src/jev.js";
import { aggregate, allPass, assertSafeOutputs, classifySlices, grade, printedTargetReconciles, sliceMetrics, CRITERIA, type EvalResult } from "./metrics.js";
import { selectCases } from "./selection.js";

interface EvalCase {
  id: string;
  source_quote_no: string;
  input: { part_no?: string; description?: string; quantity: number; material?: string; customer?: string; customer_id?: string };
  actual_unit_price: number;
  quote_date: string;
  status: string;
  target_document?: string; target_document_sha256?: string; target_transcript_sha256?: string;
  target_source_field?: string; target_printed_extension?: string; target_price_basis?: string;
  target_quote_letter?: string;
  target_unit_price?: string;
}

const argv = process.argv.slice(2);
const values: Record<string, string> = {};
const switches = new Set<string>();
let evalsetPath = "evals/evalset.jsonl";
let positional = false;
for (let i = 0; i < argv.length; i++) {
  const arg = argv[i]!;
  if (["--register", "--limit", "--sample", "--seed", "--report"].includes(arg)) {
    if (values[arg] !== undefined) throw new Error(`duplicate option ${arg}`);
    const value = argv[++i];
    if (!value || value.startsWith("--")) throw new Error(`${arg} requires a value`);
    values[arg] = value;
  } else if (["--jev", "--retrospective"].includes(arg)) {
    if (switches.has(arg)) throw new Error(`duplicate option ${arg}`);
    switches.add(arg);
  } else if (arg.startsWith("-")) throw new Error(`unknown option ${arg}`);
  else if (positional) throw new Error(`unexpected positional argument ${arg}`);
  else { evalsetPath = arg; positional = true; }
}
const registerPath = values["--register"] ?? "quotes.csv";
const reportPath = values["--report"] ?? `evals/report-${new Date().toISOString().slice(0, 10)}.md`;
if (!reportPath.endsWith(".md")) throw new Error("--report must end in .md");
const jsonPath = reportPath.slice(0, -3) + ".json";
const limitRaw = values["--limit"];
const sampleRaw = values["--sample"];
if (limitRaw !== undefined && sampleRaw !== undefined) throw new Error("--limit and --sample are mutually exclusive");
if (values["--seed"] !== undefined && sampleRaw === undefined) throw new Error("--seed requires --sample");
if (limitRaw !== undefined && !/^(0|[1-9]\d*)$/.test(limitRaw)) throw new Error("--limit must be a nonnegative safe integer");
if (sampleRaw !== undefined && !/^(0|[1-9]\d*)$/.test(sampleRaw)) throw new Error("--sample must be a nonnegative safe integer");
const limit = limitRaw === undefined ? Infinity : Number(limitRaw);
if (limitRaw !== undefined && !Number.isSafeInteger(limit)) throw new Error("--limit must be a nonnegative safe integer");
const sample = sampleRaw === undefined ? null : Number(sampleRaw);
if (sample !== null && !Number.isSafeInteger(sample)) throw new Error("--sample must be a nonnegative safe integer");
const seed = values["--seed"] ?? "keller-eval-sample-v1";
if (!seed.trim()) throw new Error("--seed must be nonempty");
const retrospective = switches.has("--retrospective");
const useJev = switches.has("--jev");
const jev = useJev ? new JevClient() : new JevClient("");
if (useJev && !jev.enabled) throw new Error("--jev requires AI_GATEWAY_API_KEY; no evaluation report was written");
assertSafeOutputs([evalsetPath, registerPath], [reportPath, jsonPath]);

const sha = (data: Buffer | string) => createHash("sha256").update(data).digest("hex");
const evalsetBytes = readFileSync(evalsetPath);
const registerBytes = readFileSync(registerPath);
const allCases = evalsetBytes.toString("utf8").split("\n").filter((line) => line.trim())
  .map((line) => JSON.parse(line) as EvalCase);
const ids = new Set<string>();
for (const c of allCases) {
  if (!c.id || ids.has(c.id)) throw new Error(`missing or duplicate case ID: ${c.id}`);
  ids.add(c.id);
}
const cases = sample === null ? allCases.slice(0, limit) : selectCases(allCases, sample, seed);
const relevantFiles = ["estimator/src/estimate.ts", "estimator/src/retrieve.ts", "estimator/src/price.ts",
  "estimator/src/register.ts", "estimator/src/jev.ts", "estimator/src/types.ts", "estimator/package-lock.json",
  "evals/run-eval.ts", "evals/metrics.ts", "evals/selection.ts"];
const codeHash = createHash("sha256");
for (const file of relevantFiles) codeHash.update(file).update("\0").update(readFileSync(new URL(`../${file}`, import.meta.url))).update("\0");
const provenance = {
  register_sha256: sha(registerBytes), evalset_sha256: sha(evalsetBytes),
  estimator_eval_source_lock_sha256: codeHash.digest("hex"), hashed_files: relevantFiles,
  run_at: new Date().toISOString(),
  selected_case_ids_sha256: sha(JSON.stringify(cases.map((c) => c.id))),
  configuration: { mode: retrospective ? "retrospective" : "cutoff-aware", limit: limitRaw === undefined ? null : limit,
    sample, seed: sample === null ? null : seed,
    jev_requested: useJev, jev_configured: jev.enabled, exclusion: "source quote_no", cutoff: retrospective ? null : "case quote_date exclusive" },
};
const reg = QuoteRegister.fromCsv(registerPath);
const results: EvalResult[] = [];
for (const [i, c] of cases.entries()) {
  const quantity = c.input.quantity;
  const sourceQuoteNo = typeof c.source_quote_no === "string" && c.source_quote_no === c.source_quote_no.trim() ?
    c.source_quote_no : "";
  const hasTarget = [c.target_document, c.target_document_sha256, c.target_transcript_sha256,
    c.target_source_field, c.target_printed_extension, c.target_price_basis,
    c.target_quote_letter, c.target_unit_price].some((field) => field !== undefined);
  const target = hasTarget ? {
    price_basis: c.target_price_basis, quote_letter: c.target_quote_letter,
    source_document: c.target_document, source_document_sha256: c.target_document_sha256,
    source_transcript_sha256: c.target_transcript_sha256, source_price_field: c.target_source_field,
    printed_extension: c.target_printed_extension, unit_price: c.target_unit_price,
  } : undefined;
  if (hasTarget && (target?.price_basis !== "customer_quote_pdf" || !target.quote_letter ||
    !target.source_document || !/^[a-f0-9]{64}$/.test(target.source_document_sha256 ?? "") ||
    !/^[a-f0-9]{64}$/.test(target.source_transcript_sha256 ?? "") ||
    !["PRICE", "QUOTEPRICE"].includes(target.source_price_field ?? "") ||
    !printedTargetReconciles(target.unit_price ?? "", quantity, target.printed_extension ?? "") ||
    Number(target.unit_price) !== c.actual_unit_price || c.status !== "unknown")) {
    throw new Error(`incomplete document target provenance: ${c.id}`);
  }
  const normalizedTarget = target as EvalResult["target"];
  const valid = Number.isFinite(c.actual_unit_price) && c.actual_unit_price > 0 &&
    Number.isSafeInteger(quantity) && quantity > 0 && !!sourceQuoteNo &&
    (retrospective ||
    (/^\d{4}-\d{2}-\d{2}$/.test(c.quote_date) && !Number.isNaN(Date.parse(`${c.quote_date}T00:00:00Z`)) &&
      new Date(`${c.quote_date}T00:00:00Z`).toISOString().slice(0, 10) === c.quote_date));
  const line = valid ? (await estimate(reg, {
    customer: retrospective ? c.input.customer : undefined, customer_id: c.input.customer_id,
    parts: [{ part_no: c.input.part_no, description: c.input.description, quantity,
      material: retrospective ? c.input.material : undefined }],
  }, { jev, exclude: new Set([sourceQuoteNo]), asOf: retrospective ? undefined : c.quote_date })).lines[0]! : null;
  const predicted = line?.unit_price ?? null;
  const priced = predicted !== null && Number.isFinite(predicted) && predicted > 0;
  const actual = Number.isFinite(c.actual_unit_price) ? c.actual_unit_price : null;
  const actualExtended = actual !== null && Number.isFinite(quantity * actual) ? quantity * actual : null;
  const predictedExtended = line?.extended_price !== null && Number.isFinite(line?.extended_price) ? line!.extended_price : null;
  const refs = (line?.analogs ?? []).map((a) => ({ quote_no: a.quote_no, quote_date: a.quote_date,
    letter_date: a.letter_date, date_stamp: a.date_stamp, rev: a.rev,
    quote_letter: a.quote_letter, price_evidence: a.price_evidence }));
  const criteria = grade({ actual: c.actual_unit_price, predicted, quantity, predicted_extended: predictedExtended,
    source_quote_no: sourceQuoteNo, quote_date: c.quote_date, retrospective, analog_refs: refs });
  const ape = priced && c.actual_unit_price > 0 ? Math.abs(predicted - c.actual_unit_price) / c.actual_unit_price : null;
  results.push({
    id: c.id, source_quote_no: sourceQuoteNo, quote_date: c.quote_date, quantity, target: normalizedTarget,
    actual, predicted: priced ? predicted : null, ape: ape !== null && Number.isFinite(ape) ? ape : null,
    confidence: Number.isFinite(line?.confidence) ? line!.confidence : 0,
    method: line?.method ?? "unreplayable", basis: line?.status_basis ?? "missing/invalid source identity, quote date, price, or quantity",
    analogs: line?.analogs.length ?? 0, status: !valid ? "unreplayable" : priced ? "priced" : "no_analog",
    analog_refs: refs, actual_extended: actualExtended, predicted_extended: predictedExtended,
    signed_unit_error: priced && actual !== null ? predicted - actual : null,
    signed_extended_error: predictedExtended !== null && actualExtended !== null ? predictedExtended - actualExtended : null,
    band_coverage: priced && actual !== null && line?.price_low !== null && line?.price_high !== null &&
      Number.isFinite(line?.price_low) && Number.isFinite(line?.price_high) ?
      actual >= line!.price_low! && actual <= line!.price_high! : null,
    slices: classifySlices({ quote_date: c.quote_date, quantity, source_status: c.status, part_no: c.input.part_no,
      source_quote_no: sourceQuoteNo, analog_part_nos: line?.analogs.map((a) => a.part_no) ?? [], confidence: line?.confidence ?? 0 }),
    criteria, all_pass: allPass(criteria),
  });
  if ((i + 1) % 25 === 0) console.error(`…${i + 1}/${cases.length}`);
}

const summary = { mode: retrospective ? "retrospective leave-one-out (future data visible)" :
  "cutoff-aware frozen-snapshot replay (not a true backtest)", ...aggregate(results), jev_configured: jev.enabled };
const slices = sliceMetrics(results);
const pct = (n: number | null) => n === null ? "n/a" : `${(n * 100).toFixed(1)}%`;
const apePct = (n: number | null) => n === null ? "n/a" : `${(n * 100).toFixed(1)}%`;
const priced = results.filter((r) => r.ape !== null).sort((a, b) => b.ape! - a.ape!);
const analogBasis = results.flatMap((r) => r.analog_refs).reduce((counts, ref) => {
  const basis = ref.price_evidence?.price_basis ?? "unknown";
  counts[basis] = (counts[basis] ?? 0) + 1;
  return counts;
}, {} as Record<string, number>);
const md = [
  `# Estimator eval — ${summary.mode} — ${provenance.run_at}`, "",
  `register: \`${registerPath}\` (${reg.rowCount} rows) · evalset: \`${evalsetPath}\` · jev configured: ${jev.enabled ? "on" : "off"}`,
  `SHA256 register: \`${provenance.register_sha256}\`; evalset: \`${provenance.evalset_sha256}\`; source+lock: \`${provenance.estimator_eval_source_lock_sha256}\``,
  `Configuration: \`${JSON.stringify(provenance.configuration)}\`. Source digest covers: ${relevantFiles.join(", ")}.`,
  `Selected case IDs SHA256: \`${provenance.selected_case_ids_sha256}\`; exposed analog reference bases: \`${JSON.stringify(analogBasis)}\`. Full target PDF/transcript/price-field and analog price-basis provenance are in the private JSON report.`,
  "Jev configured means a gateway client was available, not that every ranking, screening, or strategy call succeeded; provider failures retain deterministic fallbacks.", "",
  retrospective ? "Retrospective mode exposes later quotes and outcomes; its accuracy is not quote-time accuracy." :
    "A quote-time cutoff excludes same-day/future quotes and later-dated revisions/letters, and hides wins dated after the cutoff. Exposed analog refs include quote dates and any recorded letter/last-touch dates, revision and price evidence; missing metadata cannot be verified. Earlier records can contain unversioned edits from later dates, so the frozen extract cannot prove a true historical backtest. The fixed evalset intentionally oversamples won and recent quotes; results do not represent natural quote prevalence.", "",
  "| metric | value |", "|---|---|",
  `| cases | ${summary.cases} |`, `| priced | ${summary.priced} |`, `| no analog | ${summary.no_analog} |`,
  `| unreplayable | ${summary.unreplayable} |`, `| coverage (priced / all cases) | ${pct(summary.coverage)} |`,
  `| median APE | ${apePct(summary.median_ape)} |`, `| mean APE | ${apePct(summary.mean_ape)} |`,
  `| within ±10% | ${summary.within_10pct === null ? "n/a" : summary.within_10pct.toFixed(1) + "%"} |`,
  `| within ±20% | ${summary.within_20pct === null ? "n/a" : summary.within_20pct.toFixed(1) + "%"} |`,
  `| within ±50% | ${summary.within_50pct === null ? "n/a" : summary.within_50pct.toFixed(1) + "%"} |`,
  `| mean confidence | ${summary.mean_confidence === null ? "n/a" : summary.mean_confidence.toFixed(2)} |`,
  `| all-pass / all cases | ${summary.all_pass_count}/${summary.cases} (${pct(summary.all_pass_rate)}) |`,
  `| signed unit error (predicted minus actual, priced only) | ${summary.mean_signed_unit_error?.toFixed(4) ?? "n/a"} |`,
  `| actual extended dollars (paired priced lines) | ${summary.total_actual_extended_priced?.toFixed(2) ?? "n/a"} |`,
  `| predicted extended dollars (paired priced lines) | ${summary.total_predicted_extended_priced?.toFixed(2) ?? "n/a"} |`,
  `| signed full-line dollars (sum of priced single-line extensions) | ${summary.total_signed_extended_error?.toFixed(2) ?? "n/a"} |`,
  `| actual in predicted price band (eligible priced lines) | ${pct(summary.band_coverage)} (${summary.band_eligible} eligible) |`, "",
  `Historical cases are single quote lines; paired extended-dollar totals cover ${summary.extended_pairs}/${summary.cases} cases, not an order-level success rate. Missing prices fail all-pass and remain in all-case denominators. APE and within-X percentages retain their legacy priced-only denominator.`, "",
  "## Deterministic criteria", "", "| criterion | pass / cases |", "|---|---:|",
  ...CRITERIA.map((key) => `| ${key} | ${pct(summary.criterion_pass_rate[key])} |`), "",
  "## Diagnostic slices", "", "The development/holdout split hashes normalized part number (or source quote number if absent) into 20% holdout buckets. It is a grouped diagnostic split of the public fixed sample, not a blind unseen holdout.", "",
  "| dimension | value | cases | priced | coverage | all-pass | median APE | within ±20% (priced) | signed full-line dollars |", "|---|---|---:|---:|---:|---:|---:|---:|---:|",
  ...Object.entries(slices).flatMap(([dimension, groups]) => Object.entries(groups).map(([label, s]) =>
    `| ${dimension} | ${label} | ${s.cases} | ${s.priced} | ${pct(s.coverage)} | ${pct(s.all_pass_rate)} | ${apePct(s.median_ape)} | ${s.within_20pct === null ? "n/a" : s.within_20pct.toFixed(1) + "%"} | ${s.total_signed_extended_error?.toFixed(2) ?? "n/a"} |`)), "",
  "## Failed cases", "", "| case | status | failing criteria | reasons | analog refs (quote@date) |", "|---|---|---|---|---|",
  ...results.filter((r) => !r.all_pass).map((r) => `| ${r.id} | ${r.status} | ${CRITERIA.filter((k) => !r.criteria[k].pass).join(", ")} | ${CRITERIA.filter((k) => !r.criteria[k].pass).map((k) => r.criteria[k].reason).join("; ")} | ${r.analog_refs.map((a) => `${a.quote_no}@${a.quote_date}`).join(", ") || "—"} |`), "",
  "## Worst misses", "", "| case | actual | predicted | APE | method | analogs |", "|---|---|---|---|---|---|",
  ...priced.slice(0, 10).map((r) => `| ${r.id} | $${r.actual!.toFixed(4)} | $${r.predicted!.toFixed(4)} | ${(r.ape! * 100).toFixed(0)}% | ${r.method} | ${r.analogs} |`), "",
].join("\n");
assertSafeOutputs([evalsetPath, registerPath], [reportPath, jsonPath]);
writeFileSync(reportPath, md);
writeFileSync(jsonPath, JSON.stringify({ schema_version: 2, provenance, summary, slices, results }, null, 2));
console.log(JSON.stringify(summary, null, 2));
console.log(`wrote ${reportPath}`);
