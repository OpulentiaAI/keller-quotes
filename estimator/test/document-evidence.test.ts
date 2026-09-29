import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { estimate } from "../src/estimate.js";
import { JevClient } from "../src/jev.js";
import { buildPricedOrder, renderOrderMarkdown } from "../src/order.js";
import { QuoteRegister } from "../src/register.js";
import { retrieve } from "../src/retrieve.js";
import type { PriceEvidence, QuoteRow } from "../src/types.js";

const dir = mkdtempSync(join(tmpdir(), "keller-document-evidence-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));
const digest = "a".repeat(64);
const transcript = "b".repeat(64);
const document: PriceEvidence = {
  price_basis: "customer_quote_pdf", source_document: "OUTPUT/QuoteLetter00012345.pdf",
  source_document_sha256: digest, source_transcript_sha256: transcript, source_price_field: "PRICE",
};

function row(fields: Partial<QuoteRow> = {}): QuoteRow {
  return {
    quote_no: "12345", item_no: "1", assembly_no: "", quote_date: "2020-01-01", date_stamp: "",
    customer_id: "ACME", customer: "Acme", part_no: "P-1", description: "Bracket", rev: "",
    drawing_no: "", rfq_no: "", buyer_name: "", salesperson: "", quote_letter: "00012345",
    letter_date: "2020-01-02", quantity: 10, unit_price: 12.5, unit_cost: null,
    extended_price: 125, markup: null, del_seq: null, material: "", status: "unknown",
    won_date: "", to_quote: "", user_quote: "", newsellpri: null, comment: "", ...fields,
  };
}

function csv(rows: Record<string, string>[]): string {
  const columns = Object.keys(rows[0]!);
  return `${columns.join(",")}\n${rows.map((r) => columns.map((column) => JSON.stringify(r[column] ?? "")).join(",")).join("\n")}\n`;
}

function csvRow(fields: Record<string, string> = {}): Record<string, string> {
  const base = row();
  const values = Object.fromEntries(Object.entries(base).map(([key, value]) => [key, value == null ? "" : String(value)]));
  delete values.price_evidence;
  return { ...values, ...fields };
}

function fromCsv(rows: Record<string, string>[]): QuoteRegister {
  const path = join(dir, `register-${Math.random().toString(36).slice(2)}.csv`);
  writeFileSync(path, csv(rows));
  return QuoteRegister.fromCsv(path);
}

const metadata = {
  price_basis: "customer_quote_pdf", source_document: "OUTPUT/QuoteLetter00012345.pdf",
  source_document_sha256: digest, source_transcript_sha256: transcript, source_price_field: "PRICE",
};

describe("document-backed price evidence", () => {
  it("defaults legacy CSV and direct callers to internal calculations without changing their prices", async () => {
    const legacy = fromCsv([csvRow({ status: "open", price_basis: "" })]);
    expect(legacy.groups[0]!.head.price_evidence).toEqual({ price_basis: "internal_quote_calculation" });
    const direct = new QuoteRegister([row({ status: "open" })]);
    const request = { parts: [{ part_no: "P-1", quantity: 10 }] };
    const options = { jev: new JevClient("") };
    const first = (await estimate(legacy, request, options)).lines[0]!;
    const second = (await estimate(direct, request, options)).lines[0]!;
    expect(first.unit_price).toBe(12.5);
    expect(second.unit_price).toBe(first.unit_price);
    expect(first.analogs[0]!.price_evidence).toEqual({ price_basis: "internal_quote_calculation" });
    expect(first.warnings.join(" ")).toContain("not verified issued customer-quote prices");
    expect(first.warnings).toContain("no won-quote analogs — all references are open history");
    const explicit = fromCsv([csvRow({ price_basis: "internal_quote_calculation" })]);
    expect(explicit.groups[0]!.head.price_evidence).toEqual({ price_basis: "internal_quote_calculation" });
    const breaks = new QuoteRegister([row({ status: "open" }), row({ status: "open", quantity: 20, unit_price: 10 })]);
    expect((await estimate(breaks, { parts: [{ part_no: "P-1", quantity: 10 }] }, options)).lines[0]!.unit_price).toBe(12.5);
  });

  it("loads complete CSV provenance and carries it through JSON and order Markdown", async () => {
    const register = fromCsv([csvRow(metadata)]);
    const actual = register.groups[0]!.head;
    expect(actual.price_evidence).toEqual(document);
    const request = { parts: [{ part_no: "P-1", quantity: 10 }] };
    const line = (await estimate(register, request, { jev: new JevClient("") })).lines[0]!;
    expect(line.unit_price).toBe(12.5);
    expect(line.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(line.evidence_status).toBe("VERIFIED_CUSTOMER_PDF");
    expect(line.analogs[0]).toMatchObject({ price_evidence: document, quote_letter: "00012345", letter_date: "2020-01-02", status: "unknown" });
    expect(JSON.stringify(line)).toContain(digest);
    expect(line.warnings.join(" ")).toContain("unknown/unverified");
    expect(line.warnings.join(" ")).not.toContain("all references are open history");
    expect(line.warnings.join(" ")).not.toContain("internal quote calculations");
    const order = await buildPricedOrder(register, {
      order_id: "O-1", customer: "Acme", quote_date: "2024-06-01", charges: { shipping: 0, tax: 0 },
      parts: [{ line_id: "1", part_no: "P-1", quantity: 10 }],
    }, { registerSha256: "c".repeat(64) });
    expect(order.requires_human_review).toBe(true);
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(order.lines[0]!.evidence_status).toBe("VERIFIED_CUSTOMER_PDF");
    expect(order.lines[0]!.analogs[0]).toMatchObject({ price_evidence: document, status: "unknown" });
    const markdown = renderOrderMarkdown(order).replaceAll("\\", "");
    for (const value of [document.source_document, digest, transcript, "PRICE", "00012345", "2020-01-02", "customer_quote_pdf"]) {
      expect(markdown).toContain(value);
    }
    expect(markdown).toContain("human review required");
    expect(fromCsv([csvRow({ ...metadata, source_price_field: "QUOTEPRICE" })]).groups[0]!.head.price_evidence).toMatchObject({ source_price_field: "QUOTEPRICE" });
    const upper = fromCsv([csvRow({ ...metadata, source_document_sha256: digest.toUpperCase(), source_transcript_sha256: transcript.toUpperCase() })]);
    expect(upper.groups[0]!.head.price_evidence).toEqual(document);
    expect(new QuoteRegister([row({ price_evidence: { ...document, source_document_sha256: digest.toUpperCase() } })]).groups[0]!.head.price_evidence).toEqual(document);
  });

  it("rejects unknown basis, partial metadata, unsafe paths, invalid hashes and source fields", () => {
    const invalid: Record<string, string>[] = [
      { price_basis: "unknown" },
      { source_document: metadata.source_document },
      { ...metadata, source_document: "../OUTPUT/QuoteLetter.pdf" },
      { ...metadata, source_document: "/OUTPUT/QuoteLetter.pdf" },
      { ...metadata, source_document: "OUTPUT\\QuoteLetter.pdf" },
      { ...metadata, source_document: "OUTPUT//QuoteLetter.pdf" },
      { ...metadata, source_document: "OUTPUT/QuoteLetter.txt" },
      { ...metadata, source_transcript_sha256: "abc" },
      { ...metadata, source_price_field: "UNIT_SELL" },
      { ...metadata, source_price_field: "" },
      { ...metadata, price_basis: "internal_quote_calculation" },
    ];
    for (const fields of invalid) expect(() => fromCsv([csvRow(fields)])).toThrow();
    expect(() => new QuoteRegister([row({ price_evidence: { ...document, source_document: "../unsafe.pdf" } })])).toThrow();
    expect(() => new QuoteRegister([row({ price_evidence: document, quote_letter: "" })])).toThrow();
    expect(() => fromCsv([csvRow({ ...metadata, letter_date: "2020-02-30" })])).toThrow();
  });

  it("rejects conflicting evidence, dates, or basis among price breaks of a quote/item", () => {
    const second = row({ quantity: 20, unit_price: 10 });
    expect(() => new QuoteRegister([row({ price_evidence: document }), second])).toThrow(/conflicting price evidence/);
    expect(() => new QuoteRegister([row({ price_evidence: document }), { ...second, price_evidence: { ...document, source_price_field: "QUOTEPRICE" } }])).toThrow(/conflicting price evidence/);
    expect(() => new QuoteRegister([row({ price_evidence: document }), { ...second, price_evidence: document, letter_date: "2020-01-03" }])).toThrow(/conflicting price evidence/);
    expect(() => new QuoteRegister([row({ price_evidence: document }), { ...second, price_evidence: document, quote_date: "2020-01-03" }])).toThrow(/conflicting price evidence/);
    expect(() => fromCsv([csvRow(metadata), csvRow({ ...metadata, quantity: "20", source_document_sha256: "c".repeat(64) })])).toThrow(/conflicting price evidence/);
    expect(() => new QuoteRegister([row({ price_evidence: document }), { ...second, price_evidence: document }])).not.toThrow();
  });

  it("preserves unknown outcomes in direct cutoff retrieval without promoting future wins", () => {
    const register = new QuoteRegister([
      row({ price_evidence: document }),
      row({ quote_no: "future-win", status: "won", won_date: "2025-01-01", part_no: "P-1", price_evidence: document }),
    ]);
    const candidates = retrieve(register, { part_no: "P-1", quantity: 10 }, { asOf: "2024-01-01" });
    expect(candidates.find((candidate) => candidate.row.quote_no === "12345")?.row.status).toBe("unknown");
    expect(candidates.find((candidate) => candidate.row.quote_no === "12345")?.breaks[0]?.status).toBe("unknown");
    expect(candidates.find((candidate) => candidate.row.quote_no === "future-win")?.row.status).toBe("open");
  });
});
