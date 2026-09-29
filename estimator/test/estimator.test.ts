import { describe, expect, it } from "vitest";
import { QuoteRegister, normalizePartNo, descTokens } from "../src/register.js";
import { retrieve } from "../src/retrieve.js";
import { interpolateAtQty, price } from "../src/price.js";
import { estimate } from "../src/estimate.js";
import type { JevClient } from "../src/jev.js";
import type { Candidate } from "../src/types.js";
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

const ROWS: QuoteRow[] = [
  // quote Q1 for part ABC-123, three price breaks, won
  row({ quote_no: "000001", part_no: "ABC-123", description: "RETAINER PLATE", customer_id: "C1", customer: "ACME", quote_date: "2024-01-15", quantity: 50, unit_price: 10, status: "won", won_date: "2024-02-01" }),
  row({ quote_no: "000001", part_no: "ABC-123", description: "RETAINER PLATE", customer_id: "C1", customer: "ACME", quote_date: "2024-01-15", quantity: 100, unit_price: 9, status: "won", won_date: "2024-02-01" }),
  row({ quote_no: "000001", part_no: "ABC-123", description: "RETAINER PLATE", customer_id: "C1", customer: "ACME", quote_date: "2024-01-15", quantity: 500, unit_price: 7, status: "won", won_date: "2024-02-01" }),
  // quote Q2 same part, older, open
  row({ quote_no: "000002", part_no: "ABC-123", description: "RETAINER PLATE", customer_id: "C2", customer: "OTHER CO", quote_date: "2010-05-01", quantity: 100, unit_price: 8, status: "open" }),
  // unrelated quote
  row({ quote_no: "000003", part_no: "ZZZ-999", description: "HYDRAULIC MANIFOLD", customer_id: "C3", customer: "THIRD", quote_date: "2020-01-01", quantity: 10, unit_price: 500, status: "won" }),
];

const reg = new QuoteRegister(ROWS);

describe("register", () => {
  it("normalizes part numbers", () => {
    expect(normalizePartNo("abc-123-x")).toBe("ABC123X");
  });
  it("groups qty breaks under one quote", () => {
    expect(reg.groups.length).toBe(3);
    const g = reg.groups.find((x) => x.quote_no.startsWith("000001"))!;
    expect(g.breaks.length).toBe(3);
  });
  it("tokenizes descriptions without stopwords", () => {
    expect(descTokens("RETAINER PLATE ASSY")).toEqual(["RETAINER", "PLATE"]);
  });
});

describe("retrieve", () => {
  it("exact part_no match tops the list", () => {
    const c = retrieve(reg, { part_no: "ABC-123", quantity: 100 });
    expect(c[0]!.row.quote_no.startsWith("000001") || c[0]!.row.quote_no.startsWith("000002")).toBe(true);
    expect(c[0]!.reasons).toContain("exact part_no");
    expect(c.find((x) => x.row.part_no === "ZZZ-999")).toBeUndefined();
  });
  it("finds analogs by description when no part number", () => {
    const c = retrieve(reg, { description: "RETAINER PLATE", quantity: 10 });
    expect(c.length).toBeGreaterThan(0);
    expect(c.every((x) => x.row.part_no !== "ZZZ-999")).toBe(true);
  });
});

describe("price", () => {
  const breaks = [
    { quantity: 50, unit_price: 10 },
    { quantity: 100, unit_price: 9 },
    { quantity: 500, unit_price: 7 },
  ];
  it("interpolates log-log inside the break range", () => {
    const p = interpolateAtQty(breaks, 200)!;
    expect(p).toBeGreaterThan(7);
    expect(p).toBeLessThan(9);
  });
  it("damps extrapolation below smallest break", () => {
    const p = interpolateAtQty(breaks, 5)!;
    expect(p).toBeLessThanOrEqual(12.5);
  });
  it("returns null for empty breaks", () => {
    expect(interpolateAtQty([], 10)).toBeNull();
  });
  it("collapses repeated quantities without a zero log denominator", () => {
    const result = interpolateAtQty([
      { quantity: 10, unit_price: 10 }, { quantity: 10, unit_price: 10 },
      { quantity: 100, unit_price: 5 },
    ], 5)!;
    expect(Number.isFinite(result)).toBe(true);
    expect(result).toBeGreaterThan(10);
    expect(result).toBeLessThanOrEqual(12.5);
  });
  it("prices from candidates with weights", () => {
    const c = retrieve(reg, { part_no: "ABC-123", quantity: 100 });
    const r = price(100, c, { strategy: "median_won" });
    expect(r.unit_price).toBeGreaterThan(6);
    expect(r.unit_price).toBeLessThan(11);
    expect(r.confidence).toBeGreaterThan(0.2);
  });
  it("fits the historical break quantities instead of the requested quantity", () => {
    const c = [
      row({ quote_no: "A", quote_date: "2024-01-01", quantity: 10, unit_price: 100 }),
      row({ quote_no: "B", quote_date: "2024-01-01", quantity: 100, unit_price: 50 }),
      row({ quote_no: "C", quote_date: "2024-01-01", quantity: 1000, unit_price: 25 }),
    ].map((r) => ({ row: r, breaks: [r], score: 1, reasons: [] }));
    const fit = price(50, c, { strategy: "curve_fit", now: Date.parse("2024-01-02") });
    expect(fit.method).toBe("curve_fit");
    expect(fit.unit_price).toBeGreaterThan(50);
    expect(fit.unit_price).toBeLessThan(100);
  });
  it("normalizes regression weight per quote rather than per price break", () => {
    const single = row({ quote_no: "A", quote_date: "2024-01-01", quantity: 10, unit_price: 100 });
    const many = [10, 20, 40, 80].map((quantity) => row({ quote_no: "B", quote_date: "2024-01-01", quantity, unit_price: 10 }));
    const fit = price(25, [
      { row: single, breaks: [single], score: 1, reasons: [] },
      { row: many[0]!, breaks: many, score: 1, reasons: [] },
    ], { strategy: "curve_fit", now: Date.parse("2024-01-02") });
    expect(fit.method).toBe("curve_fit");
    expect(fit.points).toHaveLength(2);
  });
});

describe("estimate (offline fallback)", () => {
  it("rejects invalid requests before pricing", async () => {
    for (const request of [
      null,
      { parts: [null] },
      { parts: [{ quantity: "10" }] },
      { parts: [{ quantity: 0 }] },
      { parts: [{ quantity: Infinity }] },
      { parts: [{ quantity: NaN }] },
      { parts: [{ quantity: 10, description: 42 }] },
    ]) {
      await expect(estimate(reg, request as Parameters<typeof estimate>[1])).rejects.toThrow();
    }
  });
  it("produces a quote with line estimates and analogs", async () => {
    delete process.env.AI_GATEWAY_API_KEY;
    const res = await estimate(reg, {
      customer: "ACME",
      parts: [{ part_no: "ABC-123", quantity: 250, description: "RETAINER PLATE" }],
    });
    expect(res.lines.length).toBe(1);
    const l = res.lines[0]!;
    expect(l.unit_price).not.toBeNull();
    expect(l.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(l.evidence_status).toBe("HISTORICAL_INTERNAL_CALCULATION");
    expect(l.extended_price).toBeCloseTo(l.unit_price! * 250, 0);
    expect(l.analogs.length).toBeGreaterThan(0);
    expect(l.analogs[0]!.status).toBe("won");
    expect(res.jev).toBe("disabled");
  });
  it("handles parts with no analogs", async () => {
    const res = await estimate(reg, {
      parts: [{ part_no: "NOPE-000", quantity: 5 }],
    });
    expect(res.lines[0]!.unit_price).toBeNull();
    expect(res.lines[0]!.proposal_status).toBe("MISSING");
    expect(res.lines[0]!.evidence_status).toBe("NONE");
    expect(res.lines[0]!.warnings.join(" ")).toMatch(/no historical analogs|no usable/);
  });
  it("never boosts an unrelated customer's price when request identity is absent", async () => {
    const c = (quote_no: string, customer_id: string, unit_price: number) => row({
      quote_no, part_no: "PART-X", customer_id, quote_date: "2024-01-01", quantity: 10, unit_price,
    });
    const register = new QuoteRegister([
      c("low-a", "", 1), c("low-b", "", 2), c("high-a", "A", 100), c("high-b", "B", 200),
    ]);
    const res = await estimate(register, { parts: [{ part_no: "PART-X", quantity: 10 }] },
      { rankLimit: 4 });
    expect(res.lines[0]!.unit_price).toBe(2);
  });
  it("uses only quote-time history and downgrades future wins", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "old", part_no: "PART-X", customer_id: "C1", customer: "Future-resolved name", material: "future material", quote_date: "2020-01-01", date_stamp: "2020-01-02", letter_date: "", won_date: "2025-01-01", quantity: 10, unit_price: 10, status: "won" }),
      row({ quote_no: "future", part_no: "PART-X", quote_date: "2025-01-01", quantity: 10, unit_price: 20 }),
      row({ quote_no: "revision", part_no: "PART-X", quote_date: "2020-01-01", date_stamp: "2025-01-01", quantity: 10, unit_price: 30 }),
      row({ quote_no: "letter", part_no: "PART-X", quote_date: "2020-01-01", letter_date: "2025-01-01", quantity: 10, unit_price: 40 }),
      row({ quote_no: "today", part_no: "PART-X", quote_date: "2024-01-01", quantity: 10, unit_price: 50 }),
      row({ quote_no: "undated", part_no: "PART-X", quote_date: "", quantity: 10, unit_price: 60 }),
    ]);
    const res = await estimate(register, { parts: [{ part_no: "PART-X", quantity: 10 }] },
      { asOf: "2024-01-01" });
    expect(res.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["old"]);
    expect(res.lines[0]!.analogs[0]!.status).toBe("open");
    expect(res.lines[0]!.analogs[0]!.customer).toBe("");
    expect(res.lines[0]!.warnings).toContain("no won-quote analogs — all references are open history");
  });
  it("excludes a whole quote with a future-dated break and hides future outcomes from Jev", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "mixed", part_no: "PART-X", quote_date: "2020-01-01", letter_date: "2020-01-02", quantity: 10, unit_price: 10 }),
      row({ quote_no: "mixed", part_no: "PART-X", quote_date: "2020-01-01", letter_date: "2025-01-02", quantity: 100, unit_price: 1 }),
      row({ quote_no: "old", part_no: "PART-X", quote_date: "2020-01-01", won_date: "2025-02-01", status: "won", quantity: 10, unit_price: 20 }),
    ]);
    let seen: Candidate[] = [];
    const jev = {
      enabled: true,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => {
        seen = candidates;
        return { rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "jev" as const };
      },
      screenCandidate: async () => "admit" as const,
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;
    const res = await estimate(register, { parts: [{ part_no: "PART-X", quantity: 100 }] },
      { asOf: "2024-01-01", jev });
    expect(seen.map((c) => c.row.quote_no)).toEqual(["old"]);
    expect(seen[0]!.row.status).toBe("open");
    expect(seen[0]!.row.won_date).toBe("");
    expect(seen[0]!.breaks.every((b) => b.status === "open" && b.won_date === "")).toBe(true);
    expect(res.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["old"]);
    expect(res.lines[0]!.unit_price).toBe(20);
  });
  it("rejects invalid as-of dates", async () => {
    await expect(estimate(reg, { parts: [{ quantity: 10 }] }, { asOf: "2024-02-30" })).rejects.toThrow(/asOf/);
  });
});
