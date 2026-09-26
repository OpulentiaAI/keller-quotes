import { describe, expect, it } from "vitest";
import { estimate } from "../src/estimate.js";
import { JevClient } from "../src/jev.js";
import { price } from "../src/price.js";
import { QuoteRegister } from "../src/register.js";
import type { Candidate, QuoteRow } from "../src/types.js";

function row(partial: Partial<QuoteRow>): QuoteRow {
  return {
    quote_no: "", item_no: "", assembly_no: "", quote_date: "2024-01-01", date_stamp: "",
    customer_id: "", customer: "", part_no: "", description: "", rev: "", drawing_no: "",
    rfq_no: "", buyer_name: "", salesperson: "", quote_letter: "", letter_date: "",
    quantity: null, unit_price: null, unit_cost: null, extended_price: null, markup: null,
    del_seq: null, material: "", status: "open", won_date: "", to_quote: "", user_quote: "",
    newsellpri: null, comment: "", ...partial,
  };
}

function candidate(quote_no: string, quantity: number, unit_price: number, score = 1): Candidate {
  const r = row({ quote_no, quantity, unit_price });
  return { row: r, breaks: [r], score, reasons: [] };
}

describe("exact-part pricing policy", () => {
  it("gates saturated newer fuzzy evidence before ranking, screening, and strategy", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "exact", part_no: "AB-123-45", description: "RETAINER PLATE", quantity: 10, unit_price: 12, quote_date: "2020-01-01" }),
      row({ quote_no: "fuzzy", part_no: "AB-123-46", description: "RETAINER PLATE", quantity: 10, unit_price: 1000, quote_date: "2024-01-01" }),
    ]);
    const seen: string[][] = [];
    const jev = {
      enabled: true,
      rankAnalogs: async (_part: unknown, candidates: Candidate[], limit: number) => {
        expect(limit).toBe(1);
        seen.push(candidates.map((c) => c.row.quote_no));
        return { rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "jev" as const };
      },
      screenCandidate: async (_part: unknown, c: Candidate) => {
        seen.push([c.row.quote_no]);
        return "admit" as const;
      },
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        seen.push(candidates.map((c) => c.row.quote_no));
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no: " ab 123 45 ", description: "RETAINER PLATE", quantity: 10 }] },
      { jev, rankLimit: 1 });
    expect(seen).toEqual([["exact"], ["exact"], ["exact"]]);
    expect(result.lines[0]!.unit_price).toBe(12);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["exact"]);
  });

  it("retains fuzzy candidates when matching exact history has no usable price", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unpriced", part_no: "AB-123-45", description: "RETAINER PLATE", quantity: 10, unit_price: 0 }),
      row({ quote_no: "no-quantity", part_no: "AB-123-45", description: "RETAINER PLATE", quantity: 0, unit_price: 10 }),
      row({ quote_no: "nonfinite-quantity", part_no: "AB-123-45", description: "RETAINER PLATE", quantity: Infinity, unit_price: 10 }),
      row({ quote_no: "nonfinite-price", part_no: "AB-123-45", description: "RETAINER PLATE", quantity: 10, unit_price: NaN }),
      row({ quote_no: "fuzzy", part_no: "AB-123-46", description: "RETAINER PLATE", quantity: 10, unit_price: 30 }),
    ]);
    const result = await estimate(register, { parts: [{ part_no: "AB12345", description: "RETAINER PLATE", quantity: 10 }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(30);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toContain("fuzzy");
  });

  it.each([undefined, "", "---"])("keeps generic retrieval for absent or empty normalized part number %s", async (part_no) => {
    const register = new QuoteRegister([
      row({ quote_no: "first", part_no: "A-1", description: "RETAINER PLATE", quantity: 10, unit_price: 10 }),
      row({ quote_no: "second", part_no: "B-1", description: "RETAINER PLATE", quantity: 10, unit_price: 20 }),
    ]);
    const result = await estimate(register, { parts: [{ part_no, description: "RETAINER PLATE", quantity: 10 }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["first", "second"]);
  });

  it("never restores excluded or cutoff-unsafe exact quotes after retrieval", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "excluded", part_no: "AB-123", quantity: 10, unit_price: 1, quote_date: "2020-01-01" }),
      row({ quote_no: "future", part_no: "AB-123", quantity: 10, unit_price: 2, quote_date: "2025-01-01" }),
      row({ quote_no: "revised", part_no: "AB-123", quantity: 10, unit_price: 3, quote_date: "2020-01-01", date_stamp: "2025-01-01" }),
      row({ quote_no: "safe", part_no: "AB-123", quantity: 10, unit_price: 4, quote_date: "2020-01-01" }),
    ]);
    const result = await estimate(register, { parts: [{ part_no: "AB123", quantity: 10 }] },
      { asOf: "2024-01-01", exclude: new Set(["excluded"]), jev: new JevClient("") });
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["safe"]);
    expect(result.lines[0]!.unit_price).toBe(4);
  });
});

describe("quantity relevance and range warnings", () => {
  it("favors nearer historical break quantities with zero penalty at an exact quantity", () => {
    const near = candidate("near", 10, 10);
    const far = candidate("far", 1000, 100);
    const result = price(10, [near, far], { strategy: "median_won", now: Date.parse("2024-01-01") });
    expect(result.points[0]!.weight).toBeCloseTo(1);
    expect(result.points[1]!.weight).toBeCloseTo(1 / (1 + Math.log(100)));
    expect(result.unit_price).toBe(10);
  });

  it("ignores invalid breaks and handles zero and extreme finite weights without errors", () => {
    const near = candidate("near", 10, 10, 0);
    near.breaks.push(row({ quote_no: "near", quantity: 10, unit_price: Infinity }));
    near.breaks.push(row({ quote_no: "near", quantity: 0, unit_price: 5 }));
    near.breaks.push(row({ quote_no: "near", quantity: 10, unit_price: NaN }));
    const far = candidate("far", 1e300, 20);
    const result = price(1e-300, [near, far], { strategy: "median_won", now: Date.parse("2024-01-01") });
    expect(result.points[0]!.weight).toBe(0);
    expect(result.points[1]!.weight).toBeGreaterThan(0);
    expect(Number.isFinite(result.points[1]!.weight)).toBe(true);
    expect(result.unit_price).toBe(20);
  });

  it("warns when the target is outside every usable curve, even inside their combined span", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "low", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "low", part_no: "AB-123", quantity: 100, unit_price: 10 }),
      row({ quote_no: "high", part_no: "AB-123", quantity: 200, unit_price: 8 }),
      row({ quote_no: "high", part_no: "AB-123", quantity: 300, unit_price: 6 }),
      row({ quote_no: "invalid", part_no: "AB-123", quantity: 150, unit_price: Infinity }),
    ]);
    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 150 }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).not.toBeNull();
    expect(result.lines[0]!.warnings).toContain("requested quantity outside all usable analog price-break ranges — manual review needed");
  });

  it("does not warn when a usable candidate brackets the target", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "low", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "low", part_no: "AB-123", quantity: 100, unit_price: 10 }),
      row({ quote_no: "bracket", part_no: "AB-123", quantity: 100, unit_price: 9 }),
      row({ quote_no: "bracket", part_no: "AB-123", quantity: 200, unit_price: 7 }),
    ]);
    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 150 }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.warnings).not.toContain("requested quantity outside all usable analog price-break ranges — manual review needed");
  });
});
