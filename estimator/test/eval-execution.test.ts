import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
const scratch = mkdtempSync(join(tmpdir(), "keller-eval-execution-"));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const csv = join(scratch, "register.csv");
const evalset = join(scratch, "evalset.jsonl");
const report = join(scratch, "report.md");

const run = (extra: string[] = []) => {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  return spawnSync(process.execPath,
    [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), join(repo, "evals/run-eval.ts"),
      evalset, "--register", csv, "--report", report, ...extra],
    { cwd: repo, env, encoding: "utf8" });
};

describe("eval execution", () => {
  it("reports even, odd, and empty median APE accurately", () => {
    writeFileSync(csv, "quote_no,item_no,quote_date,part_no,status,quantity,unit_price\n" +
      ["A", "B", "C"].flatMap((part, i) => [
        `${part}-old,,2023-01-01,${part}${part}${part}${part},open,10,10`,
        `${part}-target,,2024-01-01,${part}${part}${part}${part},open,10,${i === 0 ? 20 : 10}`,
      ]).join("\n") + "\n");
    const cases = ["A", "B", "C"].map((part, i) => JSON.stringify({
      id: part, source_quote_no: `${part}-target`, quote_date: "2024-01-01", status: "open",
      input: { part_no: part.repeat(4), quantity: 10 }, actual_unit_price: i === 0 ? 20 : 10,
    }));
    writeFileSync(evalset, cases.join("\n") + "\n");

    for (const [limit, priced, median] of [[2, 2, 0.25], [3, 3, 0], [0, 0, null]] as const) {
      const result = run(["--limit", String(limit)]);
      expect(result.status, result.stderr).toBe(0);
      const { summary } = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
      expect(summary).toMatchObject({ priced, median_ape: median, jev_configured: false });
    }
  });

  it("fails --jev without a key before creating either report", () => {
    rmSync(report, { force: true });
    rmSync(report.replace(/\.md$/, ".json"), { force: true });
    const result = run(["--jev"]);
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("--jev requires AI_GATEWAY_API_KEY");
    expect(existsSync(report)).toBe(false);
    expect(existsSync(report.replace(/\.md$/, ".json"))).toBe(false);
  });

  it("samples independent of file order and records selected identities", () => {
    writeFileSync(csv, "quote_no,item_no,quote_date,part_no,status,quantity,unit_price\nQ-old,,2023-01-01,AAAA,open,10,10\n");
    writeFileSync(evalset, ["A", "B", "C"].map((id) => JSON.stringify({ id, source_quote_no: `Q-${id}`,
      quote_date: "2024-01-01", status: "open", input: { part_no: "AAAA", quantity: 10 },
      actual_unit_price: 10 })).join("\n") + "\n");
    const lines = readFileSync(evalset, "utf8").trim().split("\n");
    const first = run(["--sample", "2", "--seed", "repeatable"]);
    expect(first.status, first.stderr).toBe(0);
    const before = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
    writeFileSync(evalset, lines.reverse().join("\n") + "\n");
    const second = run(["--sample", "2", "--seed", "repeatable"]);
    expect(second.status, second.stderr).toBe(0);
    const after = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
    expect(after.results.map((r: { id: string }) => r.id)).toEqual(before.results.map((r: { id: string }) => r.id));
    expect(after.provenance.selected_case_ids_sha256).toBe(before.provenance.selected_case_ids_sha256);
    expect(run(["--limit", "1", "--sample", "1"]).status).not.toBe(0);
  });

  it("self-compares blank, omitted and whitespace-source cases as honest unreplayable results", () => {
    writeFileSync(csv, "quote_no,item_no,quote_date,part_no,status,quantity,unit_price\nQ-old,,2023-01-01,AAAA,open,10,10\n");
    writeFileSync(evalset, ["", undefined, "  "].map((source_quote_no, i) => JSON.stringify({
      id: `missing-${i}`, source_quote_no, quote_date: "2024-01-01", status: "unknown",
      input: { part_no: "AAAA", quantity: 10 }, actual_unit_price: 10,
    })).join("\n") + "\n");
    const result = run();
    expect(result.status, result.stderr).toBe(0);
    const data = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
    expect(data.summary).toMatchObject({ unreplayable: 3, priced: 0, coverage: 0 });
    for (const row of data.results) {
      expect(row).toMatchObject({ source_quote_no: "", status: "unreplayable" });
      expect(row.slices.source_status).toBe("unknown");
      expect(row.criteria.source_excluded).toMatchObject({ pass: false });
    }
    const jsonPath = report.replace(/\.md$/, ".json");
    const secondPath = join(scratch, "self-comparison-input.json");
    writeFileSync(secondPath, readFileSync(jsonPath));
    const compare = spawnSync(process.execPath, [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"),
      join(repo, "evals/compare.ts"), jsonPath, secondPath, "--report", join(scratch, "self-comparison.md")],
      { cwd: repo, encoding: "utf8" });
    expect(compare.status, compare.stderr).toBe(0);
  });

  it("refuses padded source IDs rather than leaking a quoted padded CSV row", () => {
    writeFileSync(csv, 'quote_no,item_no,quote_date,part_no,status,quantity,unit_price\n" Q1 ",,2023-01-01,AAAA,open,10,10\n');
    writeFileSync(evalset, JSON.stringify({ id: "padded-source", source_quote_no: " Q1 ",
      quote_date: "2024-01-01", status: "unknown", input: { part_no: "AAAA", quantity: 10 },
      actual_unit_price: 10 }) + "\n");
    const result = run();
    expect(result.status, result.stderr).toBe(0);
    const data = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
    expect(data.summary).toMatchObject({ unreplayable: 1, priced: 0, coverage: 0 });
    expect(data.results[0]).toMatchObject({ source_quote_no: "", status: "unreplayable", analog_refs: [],
      criteria: { source_excluded: { pass: false } } });
    expect(data.results[0].basis).toContain("source identity");
  });

  it("records complete document target and analog price basis, rejecting partial private targets", () => {
    const sha = "a".repeat(64);
    writeFileSync(csv, "quote_no,item_no,quote_date,date_stamp,quote_letter,letter_date,part_no,status,quantity,unit_price,price_basis,source_document,source_document_sha256,source_transcript_sha256,source_price_field\n" +
      `Q-old,,2023-01-01,2023-01-01,L1,2023-01-01,AAAA,unknown,10,10,customer_quote_pdf,OUTPUT/letter.pdf,${sha},${sha},PRICE\n`);
    const target = { id: "pdf-target", source_quote_no: "Q-new", quote_date: "2024-01-01", status: "unknown",
      input: { part_no: "AAAA", quantity: 10 }, actual_unit_price: 10,
      target_price_basis: "customer_quote_pdf", target_quote_letter: "L2", target_unit_price: "10.0000",
      target_printed_extension: "100.00", target_document: "OUTPUT/new.pdf",
      target_document_sha256: sha, target_transcript_sha256: sha, target_source_field: "PRICE" };
    writeFileSync(evalset, JSON.stringify(target) + "\n");
    const result = run();
    expect(result.status, result.stderr).toBe(0);
    const data = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
    expect(data.results[0].target).toMatchObject({ source_document_sha256: sha, unit_price: "10.0000" });
    expect(data.results[0].analog_refs[0].price_evidence).toMatchObject({ price_basis: "customer_quote_pdf",
      source_document_sha256: sha });
    delete (target as Partial<typeof target>).target_transcript_sha256;
    writeFileSync(evalset, JSON.stringify(target) + "\n");
    const invalid = run();
    expect(invalid.status).not.toBe(0);
    expect(invalid.stderr).toContain("incomplete document target provenance");
    for (const unit of ["0", "1.123456", "Infinity"]) {
      writeFileSync(evalset, JSON.stringify({ ...target, target_transcript_sha256: sha, target_unit_price: unit,
        actual_unit_price: Number(unit) }) + "\n");
      expect(run().status).not.toBe(0);
    }
  });
});
