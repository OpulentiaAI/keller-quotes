import { createHash } from "node:crypto";
import { closeSync, constants, existsSync, fchmodSync, lstatSync, openSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readReport, type Report } from "./compare.js";
import { CRITERIA, type EvalResult } from "./metrics.js";

export type ComparisonMode = "code-change" | "source-basis";
export const COMPARABILITY = ["scope", "quantity", "uom", "revision", "material", "finish", "delivery", "terms", "charges", "date"] as const;
type Match = "match" | "mismatch" | "unknown";
type Cost = { status: "unknown" | "unsupported" } | {
  status: "reviewed-estimate"; low: number; high: number; complete: boolean; evidence_sha256: string[];
};
export interface ReviewedCase {
  id: string; target_sha256: string;
  review: { reviewer: string; authors: string[]; reviewed_at: string; evidence_sha256: string[] };
  stage: "recorded" | "authenticated-issued" | "billed";
  stage_evidence_sha256: string[];
  comparability: Record<typeof COMPARABILITY[number], Match>;
  normalization?: { currency: "USD"; observed_adjustment: number; baseline_adjustment: number;
    candidate_adjustment: number; evidence_sha256: string[] };
  estimated_cost?: { baseline: Cost; candidate: Cost };
}
export interface ReviewedSidecar {
  schema_version: 1;
  binding: { baseline_report_sha256: string; candidate_report_sha256: string };
  cases: ReviewedCase[];
}

const sha = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const stable = (value: unknown): string => JSON.stringify(value ?? null, (_key, v) =>
  v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]])) : v);
function requireThat(ok: unknown, reason: string): asserts ok { if (!ok) throw new Error(reason); }
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown) => typeof v === "string" && v.trim().length > 0 && v === v.trim();
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const hashes = (v: unknown) => Array.isArray(v) && v.length > 0 && v.every(hash);
function fields(value: unknown, required: string[], optional: string[] = []) {
  requireThat(value && typeof value === "object" && !Array.isArray(value), "invalid sidecar object");
  requireThat(required.every((k) => Object.hasOwn(value, k)) &&
    Object.keys(value).every((k) => [...required, ...optional].includes(k)), "invalid sidecar fields");
}

// Bind only frozen case/target facts, not predictions, analog selection, or derived confidence slices.
export function caseTargetSha256(r: EvalResult): string {
  return sha(stable({ id: r.id, actual: r.actual, quantity: r.quantity, source_quote_no: r.source_quote_no,
    quote_date: r.quote_date, target: r.target ?? null, slices: {
      quote_era: r.slices.quote_era, quantity_band: r.slices.quantity_band,
      source_status: r.slices.source_status, split: r.slices.split } }));
}

function loadReport(path: string) {
  const report = readReport(path);
  const bytes = readFileSync(path);
  requireThat(stable(report) === stable(JSON.parse(bytes.toString("utf8"))), "report changed during read");
  const p = report.provenance;
  const manifest = (p as Report["provenance"] & { hashed_files?: string[] }).hashed_files;
  requireThat(manifest === undefined || Array.isArray(manifest) && manifest.length > 0 && manifest.every(text) &&
    new Set(manifest).size === manifest.length, "invalid source hash manifest");
  requireThat(p.selected_case_ids_sha256 === undefined || hash(p.selected_case_ids_sha256), "invalid selection hash");
  requireThat(p.configuration.sample == null || typeof p.configuration.seed === "string", "invalid seed");
  requireThat(report.summary.jev_configured === p.configuration.jev_configured, "inconsistent configuration");
  for (const r of report.results) {
    requireThat(finite(r.quantity) && [r.actual, r.predicted, r.actual_extended, r.predicted_extended,
      r.signed_unit_error, r.signed_extended_error].every((n) => n === null || finite(n)), "nonfinite case amounts");
  }
  return { report, sha256: sha(bytes) };
}

function matchReports(b: Report, c: Report, mode: ComparisonMode) {
  requireThat(mode === "code-change" || mode === "source-basis", "explicit comparison mode required");
  requireThat(b.provenance.evalset_sha256 === c.provenance.evalset_sha256, "incompatible evalset hash");
  requireThat(stable(b.provenance.configuration) === stable(c.provenance.configuration), "incompatible configuration");
  if (mode === "code-change") requireThat(b.provenance.register_sha256 === c.provenance.register_sha256, "incompatible register hash");
  else {
    requireThat(b.provenance.estimator_eval_source_lock_sha256 === c.provenance.estimator_eval_source_lock_sha256,
      "incompatible code/lock hash for source-basis comparison");
    const manifest = (r: Report) => (r.provenance as Report["provenance"] & { hashed_files?: string[] }).hashed_files;
    requireThat(stable(manifest(b)) === stable(manifest(c)), "incompatible source hash manifest");
  }
  requireThat(b.results.length === c.results.length && b.results.every((r, i) =>
    caseTargetSha256(r) === caseTargetSha256(c.results[i]!)), "incompatible cases, targets, sources, or selection");
}

function validateSidecar(s: ReviewedSidecar, binding: ReviewedSidecar["binding"], results: EvalResult[]) {
  fields(s, ["schema_version", "binding", "cases"]);
  fields(s.binding, ["baseline_report_sha256", "candidate_report_sha256"]);
  requireThat(s.schema_version === 1 && stable(s.binding) === stable(binding) && Array.isArray(s.cases), "invalid sidecar binding");
  const targets = new Map(results.map((r) => [r.id, caseTargetSha256(r)]));
  const seen = new Set<string>();
  for (const row of s.cases) {
    fields(row, ["id", "target_sha256", "review", "stage", "stage_evidence_sha256", "comparability"], ["normalization", "estimated_cost"]);
    requireThat(!seen.has(row.id) && targets.has(row.id) && row.target_sha256 === targets.get(row.id), "invalid sidecar case binding");
    seen.add(row.id);
    fields(row.review, ["reviewer", "authors", "reviewed_at", "evidence_sha256"]);
    const v = row.review;
    requireThat(text(v.reviewer) && Array.isArray(v.authors) && v.authors.length > 0 && v.authors.every(text) &&
      !v.authors.some((a) => a.toLowerCase() === v.reviewer.toLowerCase()) && typeof v.reviewed_at === "string" &&
      Number.isFinite(Date.parse(v.reviewed_at)) && new Date(v.reviewed_at).toISOString() === v.reviewed_at && hashes(v.evidence_sha256),
    "independent review claim required");
    requireThat(["recorded", "authenticated-issued", "billed"].includes(row.stage) && hashes(row.stage_evidence_sha256), "invalid stage evidence claim");
    fields(row.comparability, [...COMPARABILITY]);
    requireThat(COMPARABILITY.every((k) => ["match", "mismatch", "unknown"].includes(row.comparability[k])), "invalid comparability");
    if (row.normalization !== undefined) {
      const n = row.normalization;
      fields(n, ["currency", "observed_adjustment", "baseline_adjustment", "candidate_adjustment", "evidence_sha256"]);
      requireThat(n.currency === "USD" && [n.observed_adjustment, n.baseline_adjustment, n.candidate_adjustment].every(finite) &&
        hashes(n.evidence_sha256), "invalid normalization claim");
    }
    if (row.estimated_cost !== undefined) {
      fields(row.estimated_cost, ["baseline", "candidate"]);
      for (const cost of Object.values(row.estimated_cost)) {
        if (cost?.status === "reviewed-estimate") {
          fields(cost, ["status", "low", "high", "complete", "evidence_sha256"]);
          requireThat(finite(cost.low) && finite(cost.high) && cost.low >= 0 && cost.high >= cost.low &&
            typeof cost.complete === "boolean" && hashes(cost.evidence_sha256), "invalid estimated cost range");
        } else {
          fields(cost, ["status"]);
          requireThat(cost.status === "unknown" || cost.status === "unsupported", "invalid cost support state");
        }
      }
    }
  }
}

function reviewed(row: ReviewedCase | undefined, b: EvalResult, c: EvalResult) {
  const comparability = !row ? "unknown" : COMPARABILITY.some((k) => row.comparability[k] === "mismatch") ? "mismatch" :
    COMPARABILITY.every((k) => row.comparability[k] === "match") ? "match" : "unknown";
  const n = row?.normalization;
  const observed = n && b.actual_extended !== null ? b.actual_extended + n.observed_adjustment : null;
  function condition(r: EvalResult, key: "baseline" | "candidate") {
    const cost = row?.estimated_cost?.[key];
    const revenue = n && r.status === "priced" && r.criteria.extension_reconciles.pass && r.predicted_extended !== null ?
      r.predicted_extended + n[`${key}_adjustment`] : null;
    const usable = comparability === "match" && finite(observed) && observed > 0 && finite(revenue) && revenue > 0;
    const difference = usable ? { dollars: revenue! - observed!, relative: (revenue! - observed!) / observed! } : null;
    const margin = usable && cost?.status === "reviewed-estimate" && cost.complete ?
      { low: (revenue! - cost.high) / revenue!, high: (revenue! - cost.low) / revenue! } : null;
    return { comparable_price_difference: difference, estimated_margin_interval: margin,
      cost_support: cost?.status ?? "unknown" };
  }
  return { stage_claim: row?.stage ?? "unknown", comparability, review_claim: row ?? null,
    baseline: condition(b, "baseline"), candidate: condition(c, "candidate") };
}

const mean = (xs: number[]) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
const sum = (xs: number[]) => xs.length ? xs.reduce((a, b) => a + b, 0) : null;
function errors(rows: EvalResult[]) {
  const eligible = rows.filter((r) => r.status === "priced" && r.actual !== null && r.actual > 0);
  const signed = eligible.map((r) => (r.predicted! - r.actual!) / r.actual!);
  const ape = signed.map(Math.abs).sort((a, b) => a - b);
  const dollars = eligible.filter((r) => r.quantity > 0 && r.signed_extended_error !== null).map((r) => r.signed_extended_error!);
  return { error_cases: eligible.length, mean_ape: mean(ape), median_ape: ape.length ?
    (ape[Math.floor((ape.length - 1) / 2)]! + ape[Math.floor(ape.length / 2)]!) / 2 : null,
    p90_ape: ape.length ? ape[Math.ceil(ape.length * 0.9) - 1]! : null,
    mean_signed_relative_error: mean(signed), underquoted: signed.filter((x) => x < 0).length,
    overquoted: signed.filter((x) => x > 0).length, equal: signed.filter((x) => x === 0).length,
    mean_signed_unit_dollars: mean(eligible.map((r) => r.predicted! - r.actual!)), extension_cases: dollars.length,
    signed_extended_dollars: sum(dollars), underquote_exposure_dollars: sum(dollars.map((x) => Math.max(0, -x))),
    overquote_exposure_dollars: sum(dollars.map((x) => Math.max(0, x))), absolute_exposure_dollars: sum(dollars.map(Math.abs)) };
}
function conditionSummary(rows: EvalResult[]) {
  return { priced: rows.filter((r) => r.status === "priced").length, held: rows.filter((r) => r.status !== "priced").length,
    no_analog: rows.filter((r) => r.status === "no_analog").length, unreplayable: rows.filter((r) => r.status === "unreplayable").length,
    all_pass: rows.filter((r) => r.all_pass).length, errors: errors(rows) };
}

export function diagnoseReports(baselinePath: string, candidatePath: string, mode: ComparisonMode, sidecarPath?: string) {
  const baseline = loadReport(baselinePath), candidate = loadReport(candidatePath);
  const b = baseline.report, c = candidate.report;
  matchReports(b, c, mode);
  const binding = { baseline_report_sha256: baseline.sha256, candidate_report_sha256: candidate.sha256 };
  const sidecarBytes = sidecarPath ? readFileSync(sidecarPath) : null;
  const sidecar = sidecarBytes ? JSON.parse(sidecarBytes.toString("utf8")) as ReviewedSidecar : undefined;
  if (sidecar !== undefined) validateSidecar(sidecar, binding, b.results);
  const reviews = new Map(sidecar?.cases.map((r) => [r.id, r]));
  const pairs = b.results.map((before, i) => ({ before, after: c.results[i]! }));
  const intersection = pairs.filter(({ before, after }) => before.status === "priced" && after.status === "priced");
  const cases = pairs.map(({ before, after }) => ({ id: before.id, target_sha256: caseTargetSha256(before),
    baseline: before, candidate: after, reviewed: reviewed(reviews.get(before.id), before, after) }));
  const transitions = Object.fromEntries([...CRITERIA, "all_pass" as const].map((key) => {
    const pass = (r: EvalResult) => key === "all_pass" ? r.all_pass : r.criteria[key].pass;
    return [key, { gained: pairs.filter(({ before, after }) => !pass(before) && pass(after)).length,
      lost: pairs.filter(({ before, after }) => pass(before) && !pass(after)).length,
      pass_both: pairs.filter(({ before, after }) => pass(before) && pass(after)).length,
      fail_both: pairs.filter(({ before, after }) => !pass(before) && !pass(after)).length }];
  }));
  const reviewCounts = {
    reviewed_cases: reviews.size,
    comparability: Object.fromEntries(["match", "mismatch", "unknown"].map((v) => [v, cases.filter((r) => r.reviewed.comparability === v).length])),
    stage_claims: Object.fromEntries(["recorded", "authenticated-issued", "billed", "unknown"].map((v) => [v, cases.filter((r) => r.reviewed.stage_claim === v).length])),
    comparable_price_cases: Object.fromEntries((["baseline", "candidate"] as const).map((k) => [k, cases.filter((r) => r.reviewed[k].comparable_price_difference !== null).length])),
    unknown_comparable_price_cases: Object.fromEntries((["baseline", "candidate"] as const).map((k) => [k, cases.filter((r) => r.reviewed[k].comparable_price_difference === null).length])),
    estimated_margin_cases: Object.fromEntries((["baseline", "candidate"] as const).map((k) => [k, cases.filter((r) => r.reviewed[k].estimated_margin_interval !== null).length])),
    unknown_margin_cases: Object.fromEntries((["baseline", "candidate"] as const).map((k) => [k, cases.filter((r) => r.reviewed[k].estimated_margin_interval === null).length])),
  };
  return { schema_version: 1, mode, provenance: { ...binding, sidecar_sha256: sidecarBytes ? sha(sidecarBytes) : null,
    baseline: b.provenance, candidate: c.provenance }, summary: {
    all_cases: pairs.length, intersection_priced: intersection.length,
    newly_priced: pairs.filter(({ before, after }) => before.status !== "priced" && after.status === "priced").length,
    newly_held: pairs.filter(({ before, after }) => before.status === "priced" && after.status !== "priced").length,
    held_both: pairs.filter(({ before, after }) => before.status !== "priced" && after.status !== "priced").length,
    baseline: conditionSummary(b.results), candidate: conditionSummary(c.results),
    intersection: { baseline: errors(intersection.map((p) => p.before)), candidate: errors(intersection.map((p) => p.after)) },
    criterion_transitions: transitions, review: reviewCounts }, cases };
}
export type ObservedPriceDiagnostic = ReturnType<typeof diagnoseReports>;

// No case IDs, paths, hashes, free text, per-case values, or monetary amounts on stdout.
export function publicSummary(report: ObservedPriceDiagnostic) {
  const safeErrors = (e: ReturnType<typeof errors>) => ({ error_cases: e.error_cases, mean_ape: e.mean_ape,
    median_ape: e.median_ape, p90_ape: e.p90_ape, mean_signed_relative_error: e.mean_signed_relative_error,
    underquoted: e.underquoted, overquoted: e.overquoted, equal: e.equal });
  const safeCondition = (c: ReturnType<typeof conditionSummary>) => ({ ...c, errors: safeErrors(c.errors) });
  const s = report.summary;
  return { schema_version: report.schema_version, mode: report.mode,
    all_cases: s.all_cases, intersection_priced: s.intersection_priced, newly_priced: s.newly_priced,
    newly_held: s.newly_held, held_both: s.held_both, criterion_transitions: s.criterion_transitions, review: s.review,
    baseline: safeCondition(report.summary.baseline), candidate: safeCondition(report.summary.candidate),
    intersection: { baseline: safeErrors(report.summary.intersection.baseline), candidate: safeErrors(report.summary.intersection.candidate) },
    interpretation: "Historical diagnostic only; review/stage claims are not authenticated facts. Cheaper is not better. No commercial-success or actual-cost guarantee; human release approval required." };
}

export function writePrivateReport(path: string, report: ObservedPriceDiagnostic) {
  requireThat(isAbsolute(path) && path === resolve(path) && path.endsWith(".json"), "require a normalized absolute .json output path");
  const parent = dirname(path);
  requireThat(realpathSync(parent) === parent, "output parent aliases another path");
  const info = statSync(parent);
  requireThat(info.isDirectory() && (info.mode & 0o077) === 0 &&
    (typeof process.getuid !== "function" || info.uid === process.getuid()), "output parent must be owner-private");
  for (let dir = parent; ; dir = dirname(dir)) {
    requireThat(!existsSync(join(dir, ".git")) && !(existsSync(join(dir, "HEAD")) && existsSync(join(dir, "objects")) && existsSync(join(dir, "refs"))), "output must be outside Git");
    if (dir === dirname(dir)) break;
  }
  let exists = false;
  try { lstatSync(path); exists = true; } catch (e) { if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e; }
  requireThat(!exists, "refusing existing output or alias");
  const fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { fchmodSync(fd, 0o600); writeFileSync(fd, JSON.stringify(report, null, 2) + "\n"); } finally { closeSync(fd); }
}

function main(args: string[]) {
  try {
    const [baseline, candidate, ...options] = args;
    requireThat(baseline && candidate && !baseline.startsWith("--") && !candidate.startsWith("--"), "missing reports");
    const flags = new Map<string, string>();
    for (let i = 0; i < options.length; i += 2) {
      const key = options[i]!, value = options[i + 1];
      requireThat(["--mode", "--private-report", "--sidecar"].includes(key) && !flags.has(key) && value && !value.startsWith("--"), "invalid flags");
      flags.set(key, value);
    }
    const mode = flags.get("--mode"), output = flags.get("--private-report");
    requireThat((mode === "code-change" || mode === "source-basis") && output, "missing mode/output");
    const report = diagnoseReports(baseline, candidate, mode, flags.get("--sidecar"));
    writePrivateReport(output, report);
    console.log(JSON.stringify(publicSummary(report), null, 2));
  } catch {
    // readReport's useful operator errors can contain private identifiers; never forward them to stdout/stderr.
    console.error("Observed-price diagnostic refused: check report validity/matching, sidecar bindings, and new private output path. Usage: observed-price.ts baseline.json candidate.json --mode code-change|source-basis --private-report /private/new.json [--sidecar review.json]");
    process.exitCode = 1;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
