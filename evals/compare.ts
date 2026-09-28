import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { aggregate, allPass, assertSafeOutputs, grade, printedTargetReconciles, sliceMetrics, CRITERIA, type EvalResult } from "./metrics.js";

interface Report {
  schema_version: number;
  provenance: {
    register_sha256: string; evalset_sha256: string;
    estimator_eval_source_lock_sha256: string;
    selected_case_ids_sha256?: string;
    configuration: { mode: string; limit: number | null; sample?: number | null; seed?: string | null; jev_requested: boolean; jev_configured: boolean;
      exclusion: string; cutoff: string | null };
  };
  summary: ReturnType<typeof aggregate> & { mode: string; jev_configured: boolean };
  results: EvalResult[];
  slices: ReturnType<typeof sliceMetrics>;
}

function readReport(path: string): Report {
  const report = JSON.parse(readFileSync(path, "utf8")) as Report;
  if (report.schema_version !== 2 || !report.provenance || !report.summary || !Array.isArray(report.results) ||
    !report.results.length) throw new Error(`${path}: require nonempty schema_version 2 report`);
  for (const key of ["register_sha256", "evalset_sha256", "estimator_eval_source_lock_sha256"] as const) {
    if (!/^[a-f0-9]{64}$/.test(report.provenance[key])) throw new Error(`${path}: missing or invalid ${key}`);
  }
  const config = report.provenance.configuration;
  if (!config || !["retrospective", "cutoff-aware"].includes(config.mode) ||
    !(config.limit === null || Number.isSafeInteger(config.limit) && config.limit >= 0) ||
    (config.sample !== undefined && !(config.sample === null || Number.isSafeInteger(config.sample) && config.sample >= 0)) ||
    (config.sample !== undefined && (config.sample === null ? config.seed !== null : !config.seed || config.limit !== null)) ||
    typeof config.jev_requested !== "boolean" || typeof config.jev_configured !== "boolean" ||
    config.exclusion !== "source quote_no" || config.cutoff !== (config.mode === "retrospective" ? null : "case quote_date exclusive")) {
    throw new Error(`${path}: invalid effective configuration`);
  }
  if (report.summary.cases !== report.results.length) throw new Error(`${path}: inconsistent case count`);
  if (report.provenance.selected_case_ids_sha256) {
    const digest = createHash("sha256").update(JSON.stringify(report.results.map((r) => r.id))).digest("hex");
    if (digest !== report.provenance.selected_case_ids_sha256) throw new Error(`${path}: inconsistent selected case digest`);
  }
  const ids = new Set<string>();
  for (const r of report.results) {
    if (!r || typeof r.id !== "string" || !r.id || ids.has(r.id)) throw new Error(`${path}: duplicate or empty case ID`);
    ids.add(r.id);
    if (typeof r.source_quote_no !== "string" || (r.status !== "unreplayable" && !r.source_quote_no.trim()) ||
      r.source_quote_no !== r.source_quote_no.trim() || typeof r.quote_date !== "string" || typeof r.quantity !== "number" ||
      (r.actual !== null && typeof r.actual !== "number") || !r.slices || !r.criteria || typeof r.all_pass !== "boolean" ||
      !["priced", "no_analog", "unreplayable"].includes(r.status)) throw new Error(`${path}: malformed case ${r.id}`);
    if (r.target && (r.target.price_basis !== "customer_quote_pdf" ||
      !r.target.quote_letter || !r.target.source_document ||
      !/^[a-f0-9]{64}$/.test(r.target.source_document_sha256) ||
      !/^[a-f0-9]{64}$/.test(r.target.source_transcript_sha256) ||
      !["PRICE", "QUOTEPRICE"].includes(r.target.source_price_field) ||
      !printedTargetReconciles(r.target.unit_price, r.quantity, r.target.printed_extension) ||
      Number(r.target.unit_price) !== r.actual || r.slices.source_status !== "unknown")) {
      throw new Error(`${path}: invalid target provenance ${r.id}`);
    }
    for (const criterion of CRITERIA) if (typeof r.criteria[criterion]?.pass !== "boolean" ||
      typeof r.criteria[criterion]?.reason !== "string") throw new Error(`${path}: missing criterion ${criterion} in ${r.id}`);
    if (r.all_pass !== allPass(r.criteria)) throw new Error(`${path}: inconsistent all-pass ${r.id}`);
    if (r.status === "priced" !== (r.predicted !== null && Number.isFinite(r.predicted) && r.predicted > 0) ||
      (r.ape !== null && (!Number.isFinite(r.ape) || r.ape < 0))) throw new Error(`${path}: inconsistent price status ${r.id}`);
    const expected = grade({ actual: r.actual ?? NaN, predicted: r.predicted, quantity: r.quantity,
      predicted_extended: r.predicted_extended, source_quote_no: r.source_quote_no,
      quote_date: r.quote_date, retrospective: config.mode === "retrospective", analog_refs: r.analog_refs });
    for (const criterion of CRITERIA) if (expected[criterion].pass !== r.criteria[criterion].pass) {
      throw new Error(`${path}: inconsistent criterion ${criterion} for ${r.id}`);
    }
    const expectedApe = r.predicted !== null && r.actual !== null && r.actual > 0 ?
      Math.abs(r.predicted - r.actual) / r.actual : null;
    if (expectedApe !== r.ape) throw new Error(`${path}: inconsistent APE for ${r.id}`);
    const actualExtended = r.actual !== null && Number.isFinite(r.actual * r.quantity) ? r.actual * r.quantity : null;
    const signedUnit = r.predicted !== null && r.actual !== null ? r.predicted - r.actual : null;
    const signedExtended = r.predicted_extended !== null && actualExtended !== null ?
      r.predicted_extended - actualExtended : null;
    if (actualExtended !== r.actual_extended || signedUnit !== r.signed_unit_error ||
      signedExtended !== r.signed_extended_error) throw new Error(`${path}: inconsistent extended or signed amounts for ${r.id}`);
  }
  const computed = aggregate(report.results);
  for (const key of Object.keys(computed) as (keyof typeof computed)[]) {
    if (JSON.stringify(report.summary[key]) !== JSON.stringify(computed[key])) throw new Error(`${path}: stale or inconsistent summary ${key}`);
  }
  if (JSON.stringify(report.slices) !== JSON.stringify(sliceMetrics(report.results))) {
    throw new Error(`${path}: stale or inconsistent slices`);
  }
  return report;
}

export function compare(baseline: Report, candidate: Report) {
  for (const key of ["register_sha256", "evalset_sha256"] as const) {
    if (baseline.provenance[key] !== candidate.provenance[key]) throw new Error(`incompatible ${key}`);
  }
  if (baseline.provenance.selected_case_ids_sha256 !== candidate.provenance.selected_case_ids_sha256) {
    throw new Error("incompatible selected case digest");
  }
  if (JSON.stringify(baseline.provenance.configuration) !== JSON.stringify(candidate.provenance.configuration)) {
    throw new Error("incompatible effective configuration/mode/limit");
  }
  if (baseline.results.length !== candidate.results.length) throw new Error("incompatible case selection/count");
  const prior = new Map(baseline.results.map((r) => [r.id, r]));
  for (const r of candidate.results) {
    const b = prior.get(r.id);
    if (!b) throw new Error(`incompatible case selection: ${r.id}`);
    if (b.actual !== r.actual || b.quantity !== r.quantity || b.source_quote_no !== r.source_quote_no ||
      b.quote_date !== r.quote_date || JSON.stringify(b.target ?? null) !== JSON.stringify(r.target ?? null))
      throw new Error(`incompatible target, actual, quantity, source, or date for ${r.id}`);
    for (const key of ["quote_era", "quantity_band", "source_status", "split"] as const) {
      if (b.slices[key] !== r.slices[key]) throw new Error(`incompatible selection/slice ${key} for ${r.id}`);
    }
  }
  const before = aggregate(baseline.results);
  const after = aggregate(candidate.results);
  const delta = (a: number | null, b: number | null) => a === null || b === null ? "n/a" :
    `${((b - a) * 100).toFixed(2)} pp`;
  const apeDelta = (a: number | null, b: number | null) => a === null || b === null ? "n/a" :
    `${((b - a) * 100).toFixed(2)} pp`;
  const improved: string[] = [];
  const regressed: string[] = [];
  const newlyUnpriced: string[] = [];
  const newlyFailed: string[] = [];
  for (const r of candidate.results) {
    const b = prior.get(r.id)!;
    if (b.ape !== null && r.ape !== null && r.ape < b.ape) improved.push(r.id);
    if (b.ape !== null && r.ape !== null && r.ape > b.ape) regressed.push(r.id);
    if (b.status === "priced" && r.status !== "priced") newlyUnpriced.push(r.id);
    if (b.all_pass && !r.all_pass) newlyFailed.push(r.id);
  }
  const beforeSlices = sliceMetrics(baseline.results);
  const afterSlices = sliceMetrics(candidate.results);
  const sliceLines = Object.entries(beforeSlices).flatMap(([dimension, groups]) =>
    [...new Set([...Object.keys(groups), ...Object.keys(afterSlices[dimension] ?? {})])].sort().map((label) => {
      const old = groups[label];
      const next = afterSlices[dimension]?.[label];
      return `| ${dimension} | ${label} | ${old?.cases ?? 0} → ${next?.cases ?? 0} | ${delta(old?.coverage ?? null, next?.coverage ?? null)} | ${delta(old?.all_pass_rate ?? null, next?.all_pass_rate ?? null)} | ${apeDelta(old?.median_ape ?? null, next?.median_ape ?? null)} |`;
    }));
  const regression = (before.coverage !== null && after.coverage !== null && after.coverage < before.coverage) ||
    (before.median_ape !== null && (after.median_ape === null || after.median_ape > before.median_ape)) ||
    (before.all_pass_rate !== null && after.all_pass_rate !== null && after.all_pass_rate < before.all_pass_rate);
  const md = ["# Historical eval comparison", "",
    "Comparable case selection, actuals, quantities, source register/evalset, and effective configuration verified. Source-code digests may differ. This diagnostic comparison is not a calibrated production threshold or significance test.", "",
    `Baseline source+lock SHA256: \`${baseline.provenance.estimator_eval_source_lock_sha256}\``,
    `Candidate source+lock SHA256: \`${candidate.provenance.estimator_eval_source_lock_sha256}\``, "",
    "| metric | baseline | candidate | delta |", "|---|---:|---:|---:|",
    `| priced / all | ${before.priced}/${before.cases} | ${after.priced}/${after.cases} | ${after.priced - before.priced} |`,
    `| coverage | ${before.coverage === null ? "n/a" : (before.coverage * 100).toFixed(2) + "%"} | ${after.coverage === null ? "n/a" : (after.coverage * 100).toFixed(2) + "%"} | ${delta(before.coverage, after.coverage)} |`,
    `| all-pass | ${before.all_pass_count}/${before.cases} | ${after.all_pass_count}/${after.cases} | ${delta(before.all_pass_rate, after.all_pass_rate)} |`,
    `| median APE (priced) | ${before.median_ape === null ? "n/a" : (before.median_ape * 100).toFixed(2) + "%"} | ${after.median_ape === null ? "n/a" : (after.median_ape * 100).toFixed(2) + "%"} | ${apeDelta(before.median_ape, after.median_ape)} |`,
    `| mean APE (priced) | ${before.mean_ape === null ? "n/a" : (before.mean_ape * 100).toFixed(2) + "%"} | ${after.mean_ape === null ? "n/a" : (after.mean_ape * 100).toFixed(2) + "%"} | ${apeDelta(before.mean_ape, after.mean_ape)} |`,
    `| within ±20% (priced) | ${before.within_20pct?.toFixed(2) ?? "n/a"}% | ${after.within_20pct?.toFixed(2) ?? "n/a"}% | ${before.within_20pct === null || after.within_20pct === null ? "n/a" : (after.within_20pct - before.within_20pct).toFixed(2) + " pp"} |`,
    `| paired extended dollars (actual) | ${before.total_actual_extended_priced?.toFixed(2) ?? "n/a"} | ${after.total_actual_extended_priced?.toFixed(2) ?? "n/a"} | ${before.total_actual_extended_priced === null || after.total_actual_extended_priced === null ? "n/a" : (after.total_actual_extended_priced - before.total_actual_extended_priced).toFixed(2)} |`,
    `| paired extended dollars (predicted) | ${before.total_predicted_extended_priced?.toFixed(2) ?? "n/a"} | ${after.total_predicted_extended_priced?.toFixed(2) ?? "n/a"} | ${before.total_predicted_extended_priced === null || after.total_predicted_extended_priced === null ? "n/a" : (after.total_predicted_extended_priced - before.total_predicted_extended_priced).toFixed(2)} |`,
    `| signed full-line dollars | ${before.total_signed_extended_error?.toFixed(2) ?? "n/a"} | ${after.total_signed_extended_error?.toFixed(2) ?? "n/a"} | ${before.total_signed_extended_error === null || after.total_signed_extended_error === null ? "n/a" : (after.total_signed_extended_error - before.total_signed_extended_error).toFixed(2)} |`, "",
    "## Criterion pass rates", "", "| criterion | baseline | candidate | delta |", "|---|---:|---:|---:|",
    ...CRITERIA.map((key) => `| ${key} | ${before.criterion_pass_rate[key] === null ? "n/a" : (before.criterion_pass_rate[key]! * 100).toFixed(1) + "%"} | ${after.criterion_pass_rate[key] === null ? "n/a" : (after.criterion_pass_rate[key]! * 100).toFixed(1) + "%"} | ${delta(before.criterion_pass_rate[key], after.criterion_pass_rate[key])} |`), "",
    "## Diagnostic split and slices", "", "| dimension | value | cases | Δ coverage | Δ all-pass | Δ median APE |", "|---|---|---:|---:|---:|---:|", ...sliceLines, "",
    "## Case changes", "", `Improved APE: ${improved.join(", ") || "none"}.`, `Regressed APE: ${regressed.join(", ") || "none"}.`,
    `Newly unpriced (coverage loss): ${newlyUnpriced.join(", ") || "none"}.`,
    `New all-pass failures: ${newlyFailed.join(", ") || "none"}.`, "",
  ].join("\n");
  return { md, regression };
}

const args = process.argv.slice(2);
if (args.length && !args[0]?.startsWith("--")) {
  let failOnRegression = false;
  let output: string | undefined;
  const files: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i]!;
    if (arg === "--fail-on-regression") {
      if (failOnRegression) throw new Error("duplicate --fail-on-regression");
      failOnRegression = true;
    } else if (arg === "--report") {
      if (output) throw new Error("duplicate --report");
      output = args[++i];
      if (!output || output.startsWith("--") || !output.endsWith(".md")) throw new Error("--report requires a .md path");
    } else if (arg.startsWith("-")) throw new Error(`unknown option ${arg}`);
    else files.push(arg);
  }
  if (files.length !== 2 || !output) throw new Error("usage: compare.ts baseline.json candidate.json --report comparison.md [--fail-on-regression]");
  assertSafeOutputs(files, [output]);
  const { md, regression } = compare(readReport(files[0]!), readReport(files[1]!));
  assertSafeOutputs(files, [output]);
  writeFileSync(output, md);
  console.log(`wrote ${output}`);
  if (failOnRegression && regression) {
    console.error("diagnostic regression: coverage loss, median APE increase, or all-pass loss");
    process.exitCode = 1;
  }
} else throw new Error("usage: compare.ts baseline.json candidate.json --report comparison.md [--fail-on-regression]");
