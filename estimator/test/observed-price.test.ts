import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { linkSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { compare, readReport, type Report } from "../../evals/compare.js";
import { aggregate, allPass, grade, sliceMetrics, type EvalResult } from "../../evals/metrics.js";
import { caseTargetSha256, COMPARABILITY, diagnoseReports, publicSummary, writePrivateReport, type ReviewedSidecar } from "../../evals/observed-price.js";

const scratch = realpathSync(mkdtempSync(join(tmpdir(), "observed-price-synthetic-")));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const hash = (letter: string) => letter.repeat(64);
let serial = 0;
const path = () => join(scratch, `${serial++}.json`);
const save = (value: unknown) => { const p = path(); writeFileSync(p, JSON.stringify(value), { mode: 0o600 }); return p; };
function row(id: string, predicted: number | null, actual: number | null = 100): EvalResult {
  const quantity = 10, quote_date = "2025-01-01", source_quote_no = `fixture-source-${id}`;
  const predicted_extended = predicted === null ? null : Math.round(predicted * quantity * 100) / 100;
  const actual_extended = actual === null ? null : actual * quantity;
  const criteria = grade({ actual: actual ?? NaN, predicted, quantity, predicted_extended, source_quote_no,
    quote_date, retrospective: false, analog_refs: [] });
  return { id, source_quote_no, quote_date, quantity, actual, predicted, predicted_extended, actual_extended,
    target: actual === null ? undefined : { price_basis: "customer_quote_pdf", quote_letter: "fixture-letter", source_document: "fixture.pdf",
      source_document_sha256: hash("d"), source_transcript_sha256: hash("e"), source_price_field: "PRICE",
      unit_price: actual.toFixed(4), printed_extension: (actual * quantity).toFixed(2) },
    ape: predicted === null || actual === null ? null : Math.abs(predicted - actual) / actual,
    signed_unit_error: predicted === null || actual === null ? null : predicted - actual,
    signed_extended_error: predicted_extended === null || actual_extended === null ? null : predicted_extended - actual_extended,
    confidence: 0, method: "synthetic", basis: "synthetic", analogs: 0, analog_refs: [], band_coverage: null,
    status: actual === null ? "unreplayable" : predicted === null ? "no_analog" : "priced", criteria, all_pass: allPass(criteria),
    slices: { quote_era: "2020s", quantity_band: "1-99", source_status: "unknown", analog_match: "no analog", confidence_band: "low (<0.4)", split: "development" } };
}
function report(results: EvalResult[]): Report {
  return { schema_version: 2, provenance: { register_sha256: hash("a"), evalset_sha256: hash("b"),
    estimator_eval_source_lock_sha256: hash("c"), selected_case_ids_sha256: digest(JSON.stringify(results.map((r) => r.id))),
    configuration: { mode: "cutoff-aware", limit: null, sample: null, seed: null, jev_requested: false,
      jev_configured: false, exclusion: "source quote_no", cutoff: "case quote_date exclusive" } },
    summary: { ...aggregate(results), mode: "cutoff-aware", jev_configured: false }, results, slices: sliceMetrics(results) };
}
function pair(before: (number | null)[] = [100], after: (number | null)[] = [80]) {
  const b = report(before.map((p, i) => row(`fixture-${i}`, p)));
  const c = report(after.map((p, i) => row(`fixture-${i}`, p)));
  return { b, c, bp: save(b), cp: save(c) };
}
function sidecar(p: ReturnType<typeof pair>): ReviewedSidecar {
  return { schema_version: 1, binding: { baseline_report_sha256: digest(readFileSync(p.bp)), candidate_report_sha256: digest(readFileSync(p.cp)) },
    cases: [{ id: p.b.results[0]!.id, target_sha256: caseTargetSha256(p.b.results[0]!),
      review: { reviewer: "fixture-reviewer", authors: ["fixture-author"], reviewed_at: "2025-02-01T00:00:00.000Z", evidence_sha256: [hash("f")] },
      stage: "recorded", stage_evidence_sha256: [hash("d")],
      comparability: Object.fromEntries(COMPARABILITY.map((k) => [k, "match"])) as ReviewedSidecar["cases"][number]["comparability"],
      normalization: { currency: "USD", observed_adjustment: 0, baseline_adjustment: 0, candidate_adjustment: 0, evidence_sha256: [hash("f")] },
      estimated_cost: { baseline: { status: "unknown" }, candidate: { status: "reviewed-estimate", low: 850, high: 900, complete: true, evidence_sha256: [hash("f")] } } }] };
}

describe("matched observed-price diagnostic (synthetic only)", () => {
  it("imports the reader without executing the old CLI and preserves its register gate", () => {
    const p = pair();
    expect(readReport(p.bp).results).toHaveLength(1);
    p.c.provenance.register_sha256 = hash("f");
    expect(() => compare(p.b, p.c)).toThrow(/register/);
    expect(() => diagnoseReports(p.bp, save(p.c), "code-change")).toThrow(/register/);
    const source = diagnoseReports(p.bp, save(p.c), "source-basis");
    expect(source.provenance.baseline.register_sha256).not.toBe(source.provenance.candidate.register_sha256);
    p.c.provenance.estimator_eval_source_lock_sha256 = hash("d");
    expect(() => diagnoseReports(p.bp, save(p.c), "source-basis")).toThrow(/code\/lock/);
    p.c.provenance.register_sha256 = p.b.provenance.register_sha256;
    expect(() => diagnoseReports(p.bp, save(p.c), "code-change")).not.toThrow();
  });
  it("rejects changed evalset/target/document/transcript hashes, configuration, and case selection", () => {
    const p = pair([100, null], [80, null]);
    const mutate = (edit: (r: Report) => void) => { const next = structuredClone(p.c); edit(next); return save(next); };
    for (const mode of ["code-change", "source-basis"] as const) {
      expect(() => diagnoseReports(p.bp, mutate((r) => { r.provenance.evalset_sha256 = hash("f"); }), mode)).toThrow(/evalset/);
      for (const key of ["source_document_sha256", "source_transcript_sha256"] as const) {
        expect(() => diagnoseReports(p.bp, mutate((r) => { r.results[0]!.target![key] = hash("f"); }), mode)).toThrow(/targets/);
      }
      expect(() => diagnoseReports(p.bp, mutate((r) => { r.provenance.configuration.limit = 1; }), mode)).toThrow(/configuration/);
      expect(() => diagnoseReports(p.bp, save(report([...p.c.results].reverse())), mode)).toThrow(/selection/);
      expect(() => diagnoseReports(p.bp, save(report([row("fixture-0", 80, 101), row("fixture-1", null)])), mode)).toThrow(/targets/);
    }
    expect(() => diagnoseReports(p.bp, mutate((r) => { Object.assign(r.provenance, { hashed_files: ["different.ts"] }); }), "source-basis")).toThrow(/manifest/);
    expect(() => diagnoseReports(p.bp, mutate((r) => { r.provenance.selected_case_ids_sha256 = hash("f"); }), "code-change")).toThrow(/digest/);
    expect(() => diagnoseReports(p.bp, mutate((r) => { r.summary.priced = 99; }), "code-change")).toThrow(/summary/);
  });
  it("keeps all attempts, priced intersection, hold transitions, signed error and absolute exposure distinct", () => {
    const p = pair([80, 120, null, 110, null], [90, 80, 105, null, null]);
    const d = diagnoseReports(p.bp, p.cp, "code-change");
    expect(d.summary).toMatchObject({ all_cases: 5, intersection_priced: 2, newly_priced: 1, newly_held: 1, held_both: 1,
      baseline: { priced: 3, held: 2 }, candidate: { priced: 3, held: 2 },
      criterion_transitions: { priced_finite: { gained: 1, lost: 1, pass_both: 2, fail_both: 1 } } });
    expect(d.summary.intersection.baseline).toMatchObject({ mean_ape: 0.2, median_ape: 0.2, p90_ape: 0.2,
      mean_signed_relative_error: 0, signed_extended_dollars: 0, absolute_exposure_dollars: 400,
      underquote_exposure_dollars: 200, overquote_exposure_dollars: 200 });
    expect(d.summary.intersection.candidate.mean_signed_relative_error).toBeCloseTo(-0.15);
    expect(d.summary.intersection.candidate.mean_ape).toBeCloseTo(0.15);
    expect(d.summary.review.unknown_margin_cases.candidate).toBe(5);
    expect(row("boundary", 80).criteria.unit_within_20pct.pass).toBe(true);
    expect(row("outside", 79.99).criteria.unit_within_20pct.pass).toBe(false);
  });
  it("retains all-held and invalid-target attempts without invented errors or margins", () => {
    const r = save(report([row("held", null), row("invalid", null, null)]));
    const d = diagnoseReports(r, r, "code-change");
    expect(d.summary).toMatchObject({ all_cases: 2, intersection_priced: 0, held_both: 2,
      baseline: { held: 2, no_analog: 1, unreplayable: 1, errors: { mean_ape: null, signed_extended_dollars: null } } });
  });
  it("reports cheaper prices and negative supported estimated margins without inventing success", () => {
    const p = pair(), s = sidecar(p);
    const d = diagnoseReports(p.bp, p.cp, "code-change", save(s));
    expect(d.cases[0]!.reviewed).toMatchObject({ stage_claim: "recorded", comparability: "match",
      baseline: { estimated_margin_interval: null }, candidate: { comparable_price_difference: { dollars: -200, relative: -0.2 },
        estimated_margin_interval: { low: -0.125, high: -0.0625 } } });
    expect(d).not.toHaveProperty("success");
    for (const status of ["unknown", "unsupported"] as const) {
      s.cases[0]!.estimated_cost!.candidate = { status };
      expect(diagnoseReports(p.bp, p.cp, "code-change", save(s)).cases[0]!.reviewed.candidate.estimated_margin_interval).toBeNull();
    }
    const incomplete = sidecar(p); incomplete.cases[0]!.estimated_cost!.candidate = {
      status: "reviewed-estimate", low: 0, high: 0, complete: false, evidence_sha256: [hash("f")] };
    expect(diagnoseReports(p.bp, p.cp, "code-change", save(incomplete)).cases[0]!.reviewed.candidate.estimated_margin_interval).toBeNull();
  });
  it.each(COMPARABILITY)("does not turn a %s conflict or unknown into a comparable offer", (field) => {
    const p = pair(), s = sidecar(p);
    for (const verdict of ["mismatch", "unknown"] as const) {
      s.cases[0]!.comparability[field] = verdict;
      expect(diagnoseReports(p.bp, p.cp, "code-change", save(s)).cases[0]!.reviewed).toMatchObject({ comparability: verdict,
        candidate: { comparable_price_difference: null, estimated_margin_interval: null } });
    }
  });
  it("validates sidecar report/case bindings, review independence, and evidence claims", () => {
    const p = pair();
    for (const edit of [
      (s: ReviewedSidecar) => { s.binding.baseline_report_sha256 = hash("f"); },
      (s: ReviewedSidecar) => { s.binding.candidate_report_sha256 = hash("f"); },
      (s: ReviewedSidecar) => { s.cases[0]!.target_sha256 = hash("f"); },
      (s: ReviewedSidecar) => { s.cases.push(s.cases[0]!); },
      (s: ReviewedSidecar) => { s.cases[0]!.review.reviewer = "FIXTURE-AUTHOR"; },
      (s: ReviewedSidecar) => { s.cases[0]!.stage = "authenticated-issued"; s.cases[0]!.stage_evidence_sha256 = []; },
      (s: ReviewedSidecar) => { s.cases[0]!.review.evidence_sha256 = ["not-a-hash"]; },
    ]) { const s = sidecar(p); edit(s); expect(() => diagnoseReports(p.bp, p.cp, "code-change", save(s))).toThrow(); }
    for (const stage of ["recorded", "authenticated-issued", "billed"] as const) {
      const s = sidecar(p); s.cases[0]!.stage = stage;
      expect(diagnoseReports(p.bp, p.cp, "code-change", save(s)).summary.review.stage_claims[stage]).toBe(1);
    }
  });
  it("writes only new owner-private files outside Git and refuses hardlink/symlink/path aliases", () => {
    const p = pair(), d = diagnoseReports(p.bp, p.cp, "code-change"), output = path();
    writePrivateReport(output, d);
    expect(statSync(output).mode & 0o777).toBe(0o600);
    expect(() => writePrivateReport(output, d)).toThrow(/existing/);
    expect(() => writePrivateReport(p.bp, d)).toThrow(/existing/);
    const symlink = path(), hardlink = path(); symlinkSync(p.bp, symlink); linkSync(p.cp, hardlink);
    for (const alias of [symlink, hardlink, `${scratch}/./alias.json`]) expect(() => writePrivateReport(alias, d)).toThrow();
    const dirAlias = join(scratch, "dir-alias"); symlinkSync(scratch, dirAlias);
    expect(() => writePrivateReport(join(dirAlias, "new.json"), d)).toThrow(/aliases/);
    const gitDir = join(scratch, "fake-worktree"); mkdirSync(gitDir, { mode: 0o700 }); writeFileSync(join(gitDir, ".git"), "fixture");
    expect(() => writePrivateReport(join(gitDir, "new.json"), d)).toThrow(/outside Git/);
    const projection = JSON.stringify(publicSummary(d));
    for (const secret of ["fixture", "dollars", "sha256", "source_document", scratch]) expect(projection).not.toContain(secret);
  });
  it("runs the operator CLI with aggregate-only stdout and redacted failure output", () => {
    const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
    const p = pair(), output = path();
    const run = () => spawnSync(process.execPath, [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"),
      join(repo, "evals/observed-price.ts"), p.bp, p.cp, "--mode", "code-change", "--private-report", output], { encoding: "utf8" });
    const ok = run(); expect(ok.status, ok.stderr).toBe(0);
    expect(JSON.parse(ok.stdout)).toMatchObject({ all_cases: 1, intersection_priced: 1 });
    expect(ok.stdout).not.toMatch(/fixture|dollars|sha256/);
    p.c.results[0]!.target!.source_document_sha256 = "invalid-private-fixture";
    writeFileSync(p.cp, JSON.stringify(p.c));
    const denied = run(); expect(denied.status).toBe(1); expect(denied.stdout).toBe("");
    expect(denied.stderr).not.toContain("fixture");
  });
});
