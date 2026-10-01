import { describe, expect, it } from "vitest";
import { QuoteRegister } from "../src/register.js";
import { retrieve } from "../src/retrieve.js";
import type { QuoteRow } from "../src/types.js";

function row(partial: Partial<QuoteRow>): QuoteRow {
  return {
    quote_no: "", item_no: "", assembly_no: "", quote_date: "", date_stamp: "",
    customer_id: "", customer: "", part_no: "", description: "", rev: "",
    drawing_no: "", rfq_no: "", buyer_name: "", salesperson: "",
    quote_letter: "", letter_date: "", quantity: null, unit_price: null,
    unit_cost: null, extended_price: null, markup: null, del_seq: null,
    material: "", status: "open", won_date: "", to_quote: "", user_quote: "",
    newsellpri: null, comment: "", ...partial,
  };
}

const reg = new QuoteRegister([
  row({ quote_no: "A", part_no: "ABC-123", drawing_no: "DWG-7", description: "BRUSHED PLATE", comment: "304 STEEL", customer: "Acme Inc", customer_id: "C1", quote_date: "2020-01-01", date_stamp: "2020-02-01", letter_date: "2020-03-01", status: "won", won_date: "2020-04-01", material: "304 SS", quantity: 10, unit_price: 12 }),
  row({ quote_no: "A", part_no: "ABC-123", drawing_no: "DWG-7", description: "BRUSHED PLATE", comment: "304 STEEL", customer: "Acme Inc", customer_id: "C1", quote_date: "2020-01-01", date_stamp: "2022-02-01", letter_date: "2020-03-01", status: "won", won_date: "2022-04-01", material: "304 SS", quantity: 20, unit_price: 10 }),
  row({ quote_no: "B", part_no: "ABC1234", drawing_no: "DWG-79", description: "BRUSHED PLATE", customer: "Acme LLC", quote_date: "2019-01-01", status: "won", won_date: "2019-03-01", quantity: 10, unit_price: 11 }),
  row({ quote_no: "C", part_no: "ABC124", description: "PLATE RETAINER", quote_date: "2021-01-01", status: "open", quantity: 10, unit_price: 14 }),
  row({ quote_no: "D", part_no: "ZZZ900", drawing_no: "DWG-7", description: "304 SHEET", quote_date: "2018-01-01", quantity: 15, unit_price: 20 }),
  row({ quote_no: "E", part_no: "ABC123", quote_date: "2020-02-30", status: "won", won_date: "2020-03-01", quantity: 10, unit_price: 14 }),
  row({ quote_no: "F", part_no: "ZZZ901", drawing_no: "DWG-7", description: "304 SHEET", quote_date: "2019-01-01", letter_date: "2019-02-01", status: "won", won_date: "2022-01-01", quantity: 10, unit_price: 21 }),
]);

describe("retrieval search metadata", () => {
  it("keeps placeholder IDs available by description without treating them as part matches", () => {
    const register = new QuoteRegister([
      row({ quote_no: "placeholder", part_no: "SYN-12????", description: "BRACKET", quantity: 10, unit_price: 25 }),
      row({ quote_no: "wildcard", part_no: "SYN-12*", description: "BRACKET", quantity: 10, unit_price: 30 }),
      row({ quote_no: "exact", part_no: "SYN-12", description: "BRACKET", quantity: 10, unit_price: 40 }),
    ]);
    const found = retrieve(register, { part_no: "SYN-12", description: "BRACKET", quantity: 10 });
    expect(found.find((c) => c.row.quote_no === "exact")?.reasons).toContain("exact part_no");
    for (const quote_no of ["placeholder", "wildcard"]) {
      const candidate = found.find((c) => c.row.quote_no === quote_no)!;
      expect(candidate).toBeDefined();
      expect(candidate.reasons).toContain("desc tokens 1/1");
      expect(candidate.reasons.some((reason) => reason.startsWith("part_no") || reason === "exact part_no")).toBe(false);
    }
    const placeholderRequest = retrieve(register, { part_no: "SYN-12?", description: "BRACKET", quantity: 10 });
    expect(placeholderRequest.every((c) => c.reasons.every((reason) => reason !== "exact part_no" && !reason.startsWith("part_no")))).toBe(true);
  });

  it("ignores junk part fragments in prefix matching while keeping meaningful IDs", () => {
    const register = new QuoteRegister([
      row({ quote_no: "junk-digit", part_no: "-6", description: "PLATE", quantity: 10, unit_price: 5 }),
      row({ quote_no: "junk-short", part_no: "65", description: "PLATE", quantity: 10, unit_price: 6 }),
      row({ quote_no: "meaningful", part_no: "620-32700-00", description: "SHELF", quantity: 10, unit_price: 7 }),
    ]);
    const found = retrieve(register, { part_no: "620-32726-00", description: "SHELF MIDDLE", quantity: 10 });
    for (const quote_no of ["junk-digit", "junk-short"]) {
      const candidate = found.find((c) => c.row.quote_no === quote_no);
      expect(candidate?.reasons ?? []).not.toContain("part_no prefix");
    }
    const meaningful = found.find((c) => c.row.quote_no === "meaningful")!;
    expect(meaningful.reasons).toContain("part_no family prefix 6");
  });

  it("ranks a family-prefix analog above generic token matches", () => {
    const register = new QuoteRegister([
      row({ quote_no: "generic-a", part_no: "535-8380-00", description: "BRKT", quantity: 500, unit_price: 30 }),
      row({ quote_no: "generic-b", part_no: "P-09319-0398", description: "BRKT", quantity: 500, unit_price: 31 }),
      row({ quote_no: "family", part_no: "M-PC-0270-00", description: "PRIVACY PANEL BRKT", quantity: 500, unit_price: 12 }),
    ]);
    const found = retrieve(register, { part_no: "M-PC-0273-HS", description: "PRIVACY PANEL BRKT.", quantity: 500 }, { limit: 12 });
    const ranks = Object.fromEntries(found.map((c, i) => [c.row.quote_no, i + 1]));
    expect(ranks["family"]).toBe(1);
  });

  it("preserves exact, prefix, fuzzy and drawing match reasons", () => {
    const found = retrieve(reg, { part_no: "abc-123", drawing_ref: "dwg 7", quantity: 10 }, { limit: 20 });
    expect(found.find((c) => c.row.quote_no === "A")?.reasons).toEqual(["exact part_no", "drawing_no match", "won quote"]);
    expect(found.find((c) => c.row.quote_no === "B")?.reasons).toEqual(["part_no prefix", "drawing_no match", "won quote"]);
    expect(found.find((c) => c.row.quote_no === "C")?.reasons).toEqual(["part_no fuzzy 0.80"]);
    expect(found.find((c) => c.row.quote_no === "D")?.reasons).toEqual(["drawing_no match"]);
  });

  it("preserves description, material and customer bonuses", () => {
    const found = retrieve(reg, { description: "BRUSHED PLATE", material: "304", quantity: 10 }, { customer: "ACME COMPANY" });
    expect(found.find((c) => c.row.quote_no === "A")?.reasons).toEqual(["desc tokens 3/3", "same customer", "material match", "won quote"]);
    expect(found.find((c) => c.row.quote_no === "B")?.reasons).toEqual(["desc tokens 2/3", "same customer", "won quote"]);
    expect(found.find((c) => c.row.quote_no === "D")?.reasons).toEqual(["desc tokens 1/3"]);
  });

  it("keeps cutoff, revisions, win dates, exclusion and redaction independent per request", () => {
    const part = { part_no: "ABC123", description: "BRUSHED PLATE", material: "304", quantity: 10 };
    const late = { asOf: "2023-01-01", customerId: "C1" };
    const first = retrieve(reg, part, late);
    const early = retrieve(reg, part, { asOf: "2021-01-01", customerId: "C1" });
    expect(early.map((c) => c.row.quote_no)).not.toContain("A");
    expect(early.map((c) => c.row.quote_no)).not.toContain("E");
    const quote = first.find((c) => c.row.quote_no === "A")!;
    expect(quote.reasons).toEqual(["exact part_no", "desc tokens 3/3", "same customer_id", "material match", "won quote"]);
    expect(quote.row).toMatchObject({ status: "won", won_date: "2020-04-01", customer: "", material: "304 SS" });
    expect(quote.breaks.map((b) => b.won_date)).toEqual(["2020-04-01", "2022-04-01"]);
    const excluded = retrieve(reg, part, { ...late, exclude: new Set(["A"]) });
    expect(excluded.map((c) => c.row.quote_no)).not.toContain("A");
    expect(retrieve(reg, part, late)).toEqual(first);
    expect(reg.exactPart("ABC123")[0]!.head).toMatchObject({ customer: "Acme Inc", material: "304 SS" });
  });

  it("redacts future wins and letter material without changing original breaks", () => {
    const result = retrieve(reg, { drawing_ref: "dwg7", quantity: 10 }, { asOf: "2020-03-15" });
    const a = result.find((c) => c.row.quote_no === "A");
    expect(a).toBeUndefined();
    const early = retrieve(reg, { drawing_ref: "dwg7", quantity: 10 }, { asOf: "2021-01-01", exclude: new Set(["A"]) });
    expect(early.find((c) => c.row.quote_no === "B")?.row).toMatchObject({ status: "won", won_date: "2019-03-01", material: "", customer: "" });
    expect(early.find((c) => c.row.quote_no === "F")?.row).toMatchObject({ status: "open", won_date: "", customer: "" });
    expect(early.find((c) => c.row.quote_no === "F")?.reasons).toEqual(["drawing_no match"]);
    const late = retrieve(reg, { drawing_ref: "dwg7", quantity: 10 }, { asOf: "2023-01-01" });
    expect(late.find((c) => c.row.quote_no === "F")?.row).toMatchObject({ status: "won", won_date: "2022-01-01" });
    expect(late.find((c) => c.row.quote_no === "F")?.reasons).toEqual(["drawing_no match", "won quote"]);
    expect(retrieve(reg, { part_no: "ABC123", quantity: 10 }).find((c) => c.row.quote_no === "A")?.breaks[1]?.won_date).toBe("2022-04-01");
  });
});
