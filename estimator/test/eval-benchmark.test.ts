import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, linkSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
const scratch = mkdtempSync(join(tmpdir(), "keller-eval-benchmark-"));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const csv = join(scratch, "register.csv");
const evalset = join(scratch, "evalset.jsonl");
const baseline = join(scratch, "baseline.md");
const candidate = join(scratch, "candidate.md");
const comparison = join(scratch, "comparison.md");
const env = { ...process.env, AI_GATEWAY_API_KEY: "" };
const run = (script: string, args: string[]) => spawnSync(process.execPath,
  [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), join(repo, `evals/${script}.ts`), ...args],
  { cwd: repo, env, encoding: "utf8" });
const evalRun = (report = baseline, args: string[] = []) => run("run-eval", [evalset, "--register", csv, "--report", report, ...args]);
const compare = (a = baseline.replace(/\.md$/, ".json"), b = candidate.replace(/\.md$/, ".json"), extra: string[] = []) =>
  run("compare", [a, b, "--report", comparison, ...extra]);
const json = (path = baseline) => JSON.parse(readFileSync(path.replace(/\.md$/, ".json"), "utf8"));
function recalculateCandidate() {
  const script = `import { readFileSync, writeFileSync } from 'node:fs';
    import { aggregate, grade, allPass, sliceMetrics } from '${join(repo, "evals/metrics.ts")}';
    const p = process.argv[1]; const a = JSON.parse(readFileSync(p, 'utf8'));
    for (const r of a.results) { r.criteria = grade({ actual: r.actual, predicted: r.predicted,
      quantity: r.quantity, predicted_extended: r.predicted_extended, source_quote_no: r.source_quote_no,
      quote_date: r.quote_date, retrospective: false, analog_refs: r.analog_refs }); r.all_pass = allPass(r.criteria); }
    a.summary = { ...a.summary, ...aggregate(a.results) }; a.slices = sliceMetrics(a.results);
    writeFileSync(p, JSON.stringify(a));`;
  const res = spawnSync(process.execPath, [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), "-e", script,
    candidate.replace(/\.md$/, ".json")], { cwd: repo, env, encoding: "utf8" });
  expect(res.status, res.stderr).toBe(0);
}
const caseOf = (id: string, part: string, quantity: number, actual: number, quote = "2024-01-01") => ({
  id, source_quote_no: `${part}-target`, quote_date: quote, status: "open", input: { part_no: part, quantity }, actual_unit_price: actual,
});
function fixtures() {
  writeFileSync(csv, "quote_no,item_no,quote_date,part_no,status,quantity,unit_price\n" +
    "A-old,,2023-01-01,AAA,open,10,10\nA-target,,2024-01-01,AAA,open,10,10\n" +
    "B-old,,2023-01-01,BBB,open,10,10\nB-target,,2024-01-01,BBB,open,10,20\n");
  writeFileSync(evalset, [caseOf("good", "AAA", 10, 10), caseOf("miss", "BBB", 10, 20),
    caseOf("unpriced", "NONE", 10, 20), caseOf("unreplayable", "AAA", 10, 10, "")]
    .map((c) => JSON.stringify(c)).join("\n") + "\n");
}

describe("historical benchmark artifacts", () => {
  it("never grants all-pass to an empty rubric and rejects invalid exposed cutoff dates", () => {
    const script = `import { allPass, grade } from '${join(repo, "evals/metrics.ts")}';
      console.log(JSON.stringify({ empty: allPass({}), invalid: grade({ actual: 10, predicted: 10, quantity: 1,
        predicted_extended: 10, source_quote_no: 'target', quote_date: '2024-03-01',
        retrospective: false, analog_refs: [{quote_no:'old',quote_date:'2023-02-29'}] }).cutoff_evidence }));`;
    const res = spawnSync(process.execPath, [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), "-e", script],
      { cwd: repo, env, encoding: "utf8" });
    expect(res.status, res.stderr).toBe(0);
    expect(JSON.parse(res.stdout)).toMatchObject({ empty: false, invalid: { pass: false } });
  });
  it("grades all criteria, retains unpriced cases, and records reproducible provenance", () => {
    fixtures();
    const output = evalRun();
    expect(output.status, output.stderr).toBe(0);
    const artifact = json();
    expect(artifact.schema_version).toBe(2);
    expect(artifact.provenance.register_sha256).toBe(createHash("sha256").update(readFileSync(csv)).digest("hex"));
    expect(artifact.provenance.evalset_sha256).toBe(createHash("sha256").update(readFileSync(evalset)).digest("hex"));
    expect(artifact.provenance.estimator_eval_source_lock_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(artifact.provenance.configuration).toMatchObject({ mode: "cutoff-aware", limit: null, jev_requested: false });
    expect(artifact.provenance.run_at).toMatch(/^\d{4}-\d\d-\d\dT/);
    expect(artifact.summary).toMatchObject({ cases: 4, priced: 2, coverage: .5,
      median_ape: .25, mean_ape: .25, within_20pct: 50, all_pass_count: 1, all_pass_rate: .25 });
    const [good, miss, unpriced, unreplayable] = artifact.results;
    expect(good).toMatchObject({ all_pass: true, quantity: 10, actual_extended: 100, predicted_extended: 100,
      signed_unit_error: 0, signed_extended_error: 0, band_coverage: true });
    expect(good.analog_refs).toEqual([{ quote_no: "A-old", quote_date: "2023-01-01", quote_letter: "",
      letter_date: "", price_evidence: { price_basis: "internal_quote_calculation" } }]);
    expect(miss).toMatchObject({ all_pass: false, signed_unit_error: -10, signed_extended_error: -100 });
    expect(miss.criteria.unit_within_20pct).toMatchObject({ pass: false });
    expect(unpriced).toMatchObject({ all_pass: false, status: "no_analog", ape: null });
    expect(unpriced.criteria.priced_finite.pass).toBe(false);
    expect(unreplayable).toMatchObject({ all_pass: false, status: "unreplayable", ape: null });
    expect(artifact.summary.criterion_pass_rate.source_excluded).toBe(1);
    expect(readFileSync(baseline, "utf8")).toContain("## Failed cases");
    expect(readFileSync(baseline, "utf8")).toContain("## Diagnostic slices");
  });

  it("groups normalized parts stably and labels diagnostic holdout without changing selection", () => {
    fixtures();
    const cases = [caseOf("one", "A-1", 10, 10), caseOf("two", "a 1", 10, 10),
      caseOf("no-part", "", 10, 10)];
    writeFileSync(evalset, cases.map((c) => JSON.stringify(c)).join("\n") + "\n");
    expect(evalRun().status).toBe(0);
    const first = json();
    expect(first.results[0].slices.split).toBe(first.results[1].slices.split);
    expect(first.results[2].slices.analog_match).toBe("no analog");
    expect(Object.values(first.slices.split).reduce((n: number, s: any) => n + s.cases, 0)).toBe(3);
    expect(evalRun(candidate).status).toBe(0);
    expect(json(candidate).results.map((r: any) => r.slices)).toEqual(first.results.map((r: any) => r.slices));
  });

  it("compares like-for-like reports and rejects compatibility defects and regressions", () => {
    fixtures();
    expect(evalRun().status).toBe(0);
    expect(evalRun(candidate).status).toBe(0);
    expect(compare().status).toBe(0);
    expect(readFileSync(comparison, "utf8")).toContain("## Diagnostic split and slices");
    const original = json(candidate);
    const modified = structuredClone(original);
    modified.results[0].status = "no_analog";
    modified.results[0].predicted = null;
    modified.results[0].predicted_extended = null;
    modified.results[0].signed_unit_error = null;
    modified.results[0].signed_extended_error = null;
    modified.results[0].band_coverage = null;
    modified.results[0].ape = null;
    writeFileSync(candidate.replace(/\.md$/, ".json"), JSON.stringify(modified));
    recalculateCandidate();
    const regression = compare(undefined, undefined, ["--fail-on-regression"]);
    expect(regression.status).not.toBe(0);
    expect(regression.stderr).toContain("diagnostic regression");
    expect(readFileSync(comparison, "utf8")).toContain("Newly unpriced (coverage loss): good");
    for (const change of [
      (r: any) => { r.provenance.register_sha256 = "0".repeat(64); },
      (r: any) => { r.provenance.configuration.limit = 2; },
      (r: any) => { r.results[0].actual = 999; },
      (r: any) => { r.results[0].quantity = 999; },
      (r: any) => { r.results[0].target = { price_basis: "customer_quote_pdf", quote_letter: "L1",
        source_document: "OUTPUT/letter.pdf", source_document_sha256: "a".repeat(64),
        source_transcript_sha256: "b".repeat(64), source_price_field: "PRICE",
        unit_price: "10", printed_extension: "100.00" }; },
      (r: any) => { r.results[0].id = "miss"; },
      (r: any) => { r.results = []; r.summary.cases = 0; },
    ]) {
      const invalid = structuredClone(original);
      change(invalid);
      writeFileSync(candidate.replace(/\.md$/, ".json"), JSON.stringify(invalid));
      rmSync(comparison, { force: true });
      expect(compare().status).not.toBe(0);
      expect(existsSync(comparison)).toBe(false);
    }
  }, 20000);

  it("rejects invalid options and colliding paths before writing", () => {
    fixtures();
    for (const args of [["--limit", "NaN"], ["--limit", "-1"], ["--limit"], ["--mystery"],
      ["--report", evalset], ["--report", csv], ["--report", join(scratch, "bad.txt")]]) {
      rmSync(baseline, { force: true });
      expect(evalRun(baseline, args).status).not.toBe(0);
      expect(existsSync(baseline)).toBe(false);
    }
  });

  it("refuses output aliases without changing register, evalset, or comparison inputs", () => {
    fixtures();
    const registerBytes = readFileSync(csv);
    const evalsetBytes = readFileSync(evalset);
    const linkedMd = join(scratch, "linked.md");
    const linkedJson = join(scratch, "linked-json.json");
    symlinkSync(csv, linkedMd);
    linkSync(evalset, linkedJson);
    expect(evalRun(linkedMd).status).not.toBe(0);
    expect(evalRun(linkedJson.replace(/\.json$/, ".md")).status).not.toBe(0);
    expect(readFileSync(csv)).toEqual(registerBytes);
    expect(readFileSync(evalset)).toEqual(evalsetBytes);
    rmSync(linkedMd);
    rmSync(linkedJson);
    expect(evalRun().status).toBe(0);
    expect(evalRun(candidate).status).toBe(0);
    const baselineBytes = readFileSync(baseline.replace(/\.md$/, ".json"));
    rmSync(comparison, { force: true });
    symlinkSync(baseline.replace(/\.md$/, ".json"), comparison);
    expect(compare().status).not.toBe(0);
    expect(readFileSync(baseline.replace(/\.md$/, ".json"))).toEqual(baselineBytes);
    rmSync(comparison);
    linkSync(candidate.replace(/\.md$/, ".json"), comparison);
    expect(compare().status).not.toBe(0);
  });
});
