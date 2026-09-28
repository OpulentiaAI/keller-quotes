import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, expect, it } from "vitest";

const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
const scratch = mkdtempSync(join(tmpdir(), "document-eval-generator-"));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const source = join(scratch, "verified.csv");
const output = join(scratch, "cases.jsonl");
const sha = "a".repeat(64);
const header = "quote_no,quote_date,letter_date,quote_letter,part_no,description,customer_id,quantity,unit_price,extended_price,price_basis,status,source_document,source_document_sha256,source_transcript_sha256,source_price_field\n";
const row = (quote: string, unit = "1.23456", extension = "12.35", date = "2024-01-02") =>
  `${quote},${date},${date},L1,PART-${quote},Part,C1,10,${unit},${extension},customer_quote_pdf,unknown,OUTPUT/letter.pdf,${sha},${sha},PRICE\n`;
const run = (destination = output) => spawnSync("python3", [join(repo, "scripts/generate-document-eval.py"), source, destination, "--count", "1"],
  { cwd: repo, encoding: "utf8" });

it("selects independently of CSV order and keeps letter-event cutoff and full source precision", () => {
  writeFileSync(source, header + row("Q1") + row("Q2"));
  const first = run();
  expect(first.status, first.stderr).toBe(0);
  const selected = JSON.parse(readFileSync(output, "utf8"));
  expect(selected).toMatchObject({ quote_date: "2024-01-02", target_unit_price: "1.23456",
    target_printed_extension: "12.35", target_price_basis: "customer_quote_pdf", status: "unknown" });
  const manifest = JSON.parse(readFileSync(output.replace(/\.jsonl$/, ".manifest.json"), "utf8"));
  expect(manifest.cases_sha256).toBe(createHash("sha256").update(readFileSync(output)).digest("hex"));
  expect(statSync(output).mode & 0o777).toBe(0o600);
  rmSync(output);
  rmSync(output.replace(/\.jsonl$/, ".manifest.json"));
  writeFileSync(source, header + row("Q2") + row("Q1"));
  expect(run().status).toBe(0);
  expect(JSON.parse(readFileSync(output, "utf8"))).toEqual(selected);
});

it("rejects missing evidence, bad cutoff, unsafe quantity/precision, and duplicate identity", () => {
  const manifest = output.replace(/\.jsonl$/, ".manifest.json");
  for (const [invalid, reason] of [
    [row("Q1").replace(sha, ""), "missing/invalid document or transcript SHA"],
    [row("Q1", "1.23456", "12.34"), "price or printed extension fails reconciliation"],
    [row("Q1", "1.23456", "12.350"), "price or printed extension fails reconciliation"],
    [row("Q1", "0", "0.00"), "price or printed extension fails reconciliation"],
    [row("Q1", "1.234567", "12.35"), "quantity or unit price exceeds precision contract"],
    [row("Q1").replace(",10,1.23456,", ",9007199254740992,1.23456,"), "price or printed extension fails reconciliation"],
    [row("Q1").replace(",2024-01-02,2024-01-02,", ",2024-01-01,2024-01-02,"), "register quote_date must equal verified letter_date"],
    [row("Q1") + row("Q1"), "duplicate quote/item/quantity identity"],
    [row("Q1").replace("Q1,", '" Q1 ",'), "missing source quote or part"],
    [header.replace("quote_no,", "quote_no,quote_no,") + row("Q1").replace("Q1,", "Q1,Q1,"), "duplicate or missing CSV headers"],
    [header.replace("source_price_field\n", "source_price_field,won_date\n") + row("Q1").trimEnd() + ",2024-01-03\n", "document outcome has nonblank won_date"],
  ] as const) {
    rmSync(output, { force: true });
    rmSync(manifest, { force: true });
    writeFileSync(source, invalid.startsWith("quote_no,") ? invalid : header + invalid);
    const result = run();
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain(reason);
    expect(existsSync(output)).toBe(false);
    expect(existsSync(manifest)).toBe(false);
  }
});

it("preflights private output, symlink ancestry, and manifest collision without overwriting", () => {
  writeFileSync(source, header + row("Q1"));
  const manifest = output.replace(/\.jsonl$/, ".manifest.json");
  rmSync(output, { force: true });
  writeFileSync(manifest, "untouched");
  expect(run().status).not.toBe(0);
  expect(existsSync(output)).toBe(false);
  expect(readFileSync(manifest, "utf8")).toBe("untouched");
  rmSync(manifest);
  expect(run(join(repo, "private-customer-case.jsonl")).status).not.toBe(0);
  expect(existsSync(join(repo, "private-customer-case.jsonl"))).toBe(false);
  expect(run(source).status).not.toBe(0);
  const link = join(scratch, "link");
  symlinkSync(scratch, link);
  expect(run(join(link, "cases.jsonl")).status).not.toBe(0);
  expect(run(join(tmpdir(), "public-customer-case.jsonl")).status).not.toBe(0);
});
