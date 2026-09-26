import { createHash } from "node:crypto";
import { lstatSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { normalizePartNo } from "../estimator/src/register.js";

export const CRITERIA = ["priced_finite", "source_excluded", "cutoff_evidence", "unit_within_20pct", "extension_reconciles"] as const;

export function assertSafeOutputs(inputs: string[], outputs: string[]): void {
  const paths = [...inputs, ...outputs];
  if (new Set(paths.map((p) => resolve(p))).size !== paths.length) throw new Error("input and report paths must be distinct");
  const inputStats = inputs.map((p) => statSync(p));
  const outputStats = outputs.map((p) => {
    try {
      const link = lstatSync(p);
      if (link.isSymbolicLink()) throw new Error(`refusing symlink output: ${p}`);
      return link;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  });
  for (const [i, output] of outputStats.entries()) {
    if (!output) continue;
    if (inputStats.some((input) => input.dev === output.dev && input.ino === output.ino) ||
      outputStats.some((other, j) => j !== i && other !== null && other.dev === output.dev && other.ino === output.ino)) {
      throw new Error(`output aliases an input or another output: ${outputs[i]}`);
    }
  }
}
export type Criterion = typeof CRITERIA[number];
export type Verdict = { pass: boolean; reason: string };
export type SliceTags = { quote_era: string; quantity_band: string; source_status: string; analog_match: string; confidence_band: string; split: "development" | "holdout" };
export interface EvalResult {
  id: string;
  source_quote_no: string;
  quote_date: string;
  quantity: number;
  actual: number | null;
  predicted: number | null;
  ape: number | null;
  confidence: number;
  method: string;
  basis: string;
  analogs: number;
  status: "priced" | "no_analog" | "unreplayable";
  analog_refs: { quote_no: string; quote_date: string }[];
  actual_extended: number | null;
  predicted_extended: number | null;
  signed_unit_error: number | null;
  signed_extended_error: number | null;
  band_coverage: boolean | null;
  slices: SliceTags;
  criteria: Record<Criterion, Verdict>;
  all_pass: boolean;
}

export function diagnosticSplit(partNo: string | undefined, sourceQuoteNo: string): "development" | "holdout" {
  const key = normalizePartNo(partNo ?? "") || sourceQuoteNo;
  const bucket = createHash("sha256").update(key).digest().readUInt32BE(0) % 100;
  return bucket < 20 ? "holdout" : "development";
}

export function classifySlices(input: {
  quote_date: string; quantity: number; source_status: string; part_no?: string;
  source_quote_no: string; analog_part_nos: string[]; confidence: number;
}): SliceTags {
  const year = Number(input.quote_date.slice(0, 4));
  const quote_era = !/^\d{4}-/.test(input.quote_date) || !Number.isFinite(year) ? "undated" :
    year < 2000 ? "pre-2000" : year < 2010 ? "2000s" : year < 2020 ? "2010s" : "2020s";
  const quantity_band = !Number.isFinite(input.quantity) || input.quantity <= 0 ? "invalid" :
    input.quantity < 100 ? "1-99" : input.quantity < 1000 ? "100-999" : input.quantity < 10000 ? "1000-9999" : "10000+";
  const part = normalizePartNo(input.part_no ?? "");
  const analog_match = input.analog_part_nos.length === 0 ? "no analog" :
    part && input.analog_part_nos.some((p) => normalizePartNo(p) === part) ? "exact part" : "other analog";
  const confidence_band = !Number.isFinite(input.confidence) ? "invalid" :
    input.confidence < 0.4 ? "low (<0.4)" : input.confidence < 0.7 ? "medium (0.4-0.69)" : "high (>=0.7)";
  return { quote_era, quantity_band, source_status: input.source_status === "won" ? "won" : "open",
    analog_match, confidence_band, split: diagnosticSplit(input.part_no, input.source_quote_no) };
}

export function grade(input: {
  actual: number; predicted: number | null; quantity: number; predicted_extended: number | null;
  source_quote_no: string; quote_date: string; retrospective: boolean;
  analog_refs: { quote_no: string; quote_date: string }[];
}): Record<Criterion, Verdict> {
  const priced = input.predicted !== null && Number.isFinite(input.predicted) && input.predicted > 0;
  const validActual = Number.isFinite(input.actual) && input.actual > 0;
  const validQuantity = Number.isFinite(input.quantity) && input.quantity > 0;
  const sourceLeak = input.analog_refs.find((r) => r.quote_no === input.source_quote_no);
  const validDate = (date: string) => /^\d{4}-\d{2}-\d{2}$/.test(date) &&
    !Number.isNaN(Date.parse(`${date}T00:00:00Z`)) && new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) === date;
  const invalidDate = input.analog_refs.find((r) => !validDate(r.quote_date) || r.quote_date >= input.quote_date);
  const cutoffValid = validDate(input.quote_date);
  const expected = priced && validQuantity ? Math.round(input.predicted! * input.quantity * 100) / 100 : null;
  const extensionPass = expected !== null && input.predicted_extended !== null &&
    Number.isFinite(input.predicted_extended) &&
    Math.abs(input.predicted_extended - expected) <= 0.01 + input.quantity * 0.00005 + 1e-8;
  return {
    priced_finite: { pass: priced, reason: priced ? "finite positive unit price" : "missing or nonfinite/nonpositive unit price" },
    source_excluded: { pass: !sourceLeak, reason: sourceLeak ? `source quote ${sourceLeak.quote_no} appears in exposed analogs` : "source absent from exposed analogs; estimator exclusion requested" },
    cutoff_evidence: { pass: !input.retrospective && cutoffValid && !invalidDate,
      reason: input.retrospective ? "retrospective mode does not enforce quote-date cutoff" : !cutoffValid ? "invalid case cutoff date" :
        invalidDate ? `exposed analog ${invalidDate.quote_no} dated ${invalidDate.quote_date} is not before cutoff` :
          "exposed analog quote dates precede cutoff; revision/letter dates are not exposed (estimator enforces those filters)" },
    unit_within_20pct: { pass: priced && validActual && Math.abs(input.predicted! - input.actual) / input.actual <= 0.2,
      reason: !priced || !validActual ? "unit price or actual unavailable/invalid" :
        `absolute unit error ${(100 * Math.abs(input.predicted! - input.actual) / input.actual).toFixed(2)}%` },
    extension_reconciles: { pass: extensionPass,
      reason: extensionPass ? "finite extension reconciles within displayed four-decimal unit precision" : "extension missing, nonfinite, or inconsistent with unit × quantity" },
  };
}

export function allPass(criteria: Partial<Record<Criterion, Verdict>>): boolean {
  return CRITERIA.length > 0 && CRITERIA.every((key) => criteria[key]?.pass === true);
}

const mean = (xs: number[]) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
const median = (xs: number[]) => xs.length ? (xs[Math.floor((xs.length - 1) / 2)]! + xs[Math.floor(xs.length / 2)]!) / 2 : null;

export function aggregate(results: EvalResult[]) {
  const priced = results.filter((r) => r.status === "priced" && r.ape !== null && Number.isFinite(r.ape));
  const apes = priced.map((r) => r.ape!).sort((a, b) => a - b);
  const pctWithin = (t: number) => priced.length ? priced.filter((r) => r.ape! <= t).length / priced.length * 100 : null;
  const signed = priced.map((r) => r.signed_unit_error).filter((n): n is number => n !== null && Number.isFinite(n));
  const extension = results.map((r) => r.signed_extended_error).filter((n): n is number => n !== null && Number.isFinite(n));
  const pairedExtensions = results.filter((r) => r.actual_extended !== null && Number.isFinite(r.actual_extended) &&
    r.predicted_extended !== null && Number.isFinite(r.predicted_extended));
  const bandEligible = results.filter((r) => r.band_coverage !== null);
  return {
    cases: results.length, priced: priced.length,
    no_analog: results.filter((r) => r.status === "no_analog").length,
    unreplayable: results.filter((r) => r.status === "unreplayable").length,
    coverage: results.length ? priced.length / results.length : null,
    median_ape: median(apes), mean_ape: mean(apes),
    within_10pct: pctWithin(0.1), within_20pct: pctWithin(0.2), within_50pct: pctWithin(0.5),
    mean_confidence: mean(results.map((r) => r.confidence)),
    all_pass_count: results.filter((r) => r.all_pass).length,
    all_pass_rate: results.length ? results.filter((r) => r.all_pass).length / results.length : null,
    criterion_pass_rate: Object.fromEntries(CRITERIA.map((key) => [key, results.length ? results.filter((r) => r.criteria[key]?.pass === true).length / results.length : null])) as Record<Criterion, number | null>,
    mean_signed_unit_error: mean(signed), total_signed_extended_error: extension.length ? extension.reduce((a, b) => a + b, 0) : null,
    total_actual_extended_priced: pairedExtensions.length ? pairedExtensions.reduce((n, r) => n + r.actual_extended!, 0) : null,
    total_predicted_extended_priced: pairedExtensions.length ? pairedExtensions.reduce((n, r) => n + r.predicted_extended!, 0) : null,
    extended_pairs: pairedExtensions.length,
    band_coverage: bandEligible.length ? bandEligible.filter((r) => r.band_coverage).length / bandEligible.length : null,
    band_eligible: bandEligible.length,
  };
}

export function sliceMetrics(results: EvalResult[]) {
  const out: Record<string, Record<string, ReturnType<typeof aggregate>>> = {};
  for (const dimension of ["quote_era", "quantity_band", "source_status", "analog_match", "confidence_band", "split"] as const) {
    out[dimension] = {};
    const labels = [...new Set(results.map((r) => r.slices[dimension]))].sort();
    for (const label of labels) out[dimension]![label] = aggregate(results.filter((r) => r.slices[dimension] === label));
  }
  return out;
}
