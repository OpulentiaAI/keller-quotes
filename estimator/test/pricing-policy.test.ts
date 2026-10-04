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

  it("keeps exact and part-number prefix evidence ahead of weaker Jev-ranked analogs", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unrelated", part_no: "SYN-PL-900", description: "BRACKET", quantity: 50, unit_price: 100 }),
      row({ quote_no: "prefix", part_no: "SYN-PL-70", description: "FACEPLATE", quantity: 50, unit_price: 6 }),
    ]);
    const seen: string[][] = [];
    const jev = {
      enabled: true,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => ({
        rankedIds: candidates.map((c) => c.row.quote_no).reverse(), probabilities: {}, source: "jev" as const,
      }),
      screenCandidate: async (_part: unknown, c: Candidate) => {
        seen.push([c.row.quote_no]);
        return "reject" as const;
      },
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["prefix"]);
        return "median_won" as const;
      },
    } as unknown as JevClient;

    const result = await estimate(register,
      { parts: [{ part_no: "SYN-PL-708", description: "BRACKET", quantity: 50 }] }, { jev });
    expect(seen[0]).toEqual(["prefix"]);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["prefix"]);
    expect(result.lines[0]!.unit_price).toBe(6);
  });

  it("does not let a placeholder ID hide actual exact-part price history", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "placeholder", part_no: "SYN-12?", description: "BRACKET", quantity: 10, unit_price: 90 }),
      row({ quote_no: "exact", part_no: "SYN-12", description: "BRACKET", quantity: 10, unit_price: 25 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["exact"]);
        return { rankedIds: ["exact"], probabilities: {}, source: "jev" as const };
      },
      screenCandidate: async () => "admit" as const,
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no: "SYN-12", description: "BRACKET", quantity: 10 }] }, { jev });
    expect(result.lines[0]!.unit_price).toBe(25);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["exact"]);
  });

  it.each(["SYN-12????", "SYN-12*"])("does not promote placeholder part number %s ahead of Jev's choice", async (part_no) => {
    const register = new QuoteRegister([
      row({ quote_no: "placeholder", part_no, description: "BRACKET", quantity: 10, unit_price: 90 }),
      row({ quote_no: "related", part_no: "SYN-1201", description: "BRACKET", quantity: 10, unit_price: 25 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({ rankedIds: ["related", "placeholder"], probabilities: {}, source: "jev" as const }),
      screenCandidate: async () => "quarantine" as const,
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no: "SYN-1202", description: "BRACKET", quantity: 10 }] }, { jev });
    expect(result.lines[0]!.unit_price).toBe(25);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["related"]);
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

describe("usable fallback pricing evidence before screening budgets", () => {
  it.each([undefined, "REQ-77"])("does not spend fallback screening slots on unusable fuzzy history for part %s", async (part_no) => {
    const history = { description: "RETAINER PLATE", quantity: 10, quote_date: "2024-01-01" };
    const register = new QuoteRegister([
      row({ ...history, quote_no: "missing-price", unit_price: null }),
      row({ ...history, quote_no: "zero-price", unit_price: 0 }),
      row({ ...history, quote_no: "negative-price", unit_price: -10 }),
      row({ ...history, quote_no: "missing-quantity", quantity: null, unit_price: 10 }),
      row({ ...history, quote_no: "zero-quantity", quantity: 0, unit_price: 10 }),
      row({ ...history, quote_no: "nonfinite-quantity", quantity: Infinity, unit_price: 10 }),
      row({ ...history, quote_no: "nonfinite-price", unit_price: NaN }),
      row({ ...history, quote_no: "usable", unit_price: 22, quote_date: "2020-01-01" }),
      row({ ...history, quote_no: "second-usable", unit_price: 30, quote_date: "2019-01-01" }),
    ]);
    const seen: string[] = [];
    const jev = {
      enabled: false,
      rankAnalogs: async (_part: unknown, candidates: Candidate[], limit: number) => {
        expect(limit).toBe(2);
        expect(candidates.map((c) => c.row.quote_no)).toContain("missing-price");
        expect(candidates.map((c) => c.row.quote_no)).toContain("usable");
        return { rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "fallback" as const };
      },
      screenCandidate: async (_part: unknown, c: Candidate) => {
        seen.push(c.row.quote_no);
        return "admit" as const;
      },
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["usable"]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no, description: "RETAINER PLATE", quantity: 10 }] },
      { jev, rankLimit: 2, screenTopN: 1 });
    expect(seen).toEqual(["usable"]);
    expect(result.lines[0]!.unit_price).toBe(22);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(result.lines[0]!.warnings).toContain("screening budget skipped 1 analog");
  });

  it("applies the same usable-break gate when an enabled ranker falls back", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unpriced", description: "RETAINER PLATE", quantity: 10, quote_date: "2024-01-01" }),
      row({ quote_no: "usable", description: "RETAINER PLATE", quantity: 10, unit_price: 22, quote_date: "2020-01-01" }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({ rankedIds: ["unpriced", "usable"], probabilities: {}, source: "fallback" as const }),
      screenCandidate: async (_part: unknown, c: Candidate) => {
        expect(c.row.quote_no).toBe("usable");
        return "admit" as const;
      },
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ description: "RETAINER PLATE", quantity: 10 }] },
      { jev, screenTopN: 1 });
    expect(result.lines[0]!.unit_price).toBe(22);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
  });

  it("retains the evidence-present hold when all retrieved breaks are unusable", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unpriced", description: "RETAINER PLATE", quantity: 10, unit_price: null }),
    ]);
    const result = await estimate(register, { parts: [{ description: "RETAINER PLATE", quantity: 10 }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.evidence_status).toBe("PRESENT_BUT_NO_USABLE_PRICE");
    expect(result.lines[0]!.proposal_status).toBe("MISSING");
    expect(result.lines[0]!.analogs).toEqual([]);
  });

  it("does not bypass admission for a usable fuzzy candidate", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "usable", description: "RETAINER PLATE", quantity: 10, unit_price: 22 }),
    ]);
    const jev = {
      enabled: false,
      rankAnalogs: async () => ({ rankedIds: ["usable"], probabilities: {}, source: "fallback" as const }),
      screenCandidate: async () => "reject" as const,
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates).toEqual([]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ description: "RETAINER PLATE", quantity: 10 }] }, { jev });
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.analogs).toEqual([]);
    expect(result.lines[0]!.warnings).toContain("rejected analog usable");
  });

  it("does not restore excluded, future or revised fuzzy sources while removing unusable history", async () => {
    const history = { description: "RETAINER PLATE", quantity: 10, unit_price: 22 };
    const register = new QuoteRegister([
      row({ ...history, quote_no: "excluded", quote_date: "2020-01-01" }),
      row({ ...history, quote_no: "future", quote_date: "2025-01-01" }),
      row({ ...history, quote_no: "revised", quote_date: "2020-01-01", date_stamp: "2025-01-01" }),
      row({ ...history, quote_no: "unpriced", quote_date: "2023-01-01", unit_price: null }),
      row({ ...history, quote_no: "safe", quote_date: "2020-01-01" }),
    ]);
    const result = await estimate(register, { parts: [{ description: "RETAINER PLATE", quantity: 10 }] },
      { jev: new JevClient(""), exclude: new Set(["excluded"]), asOf: "2024-01-01", screenTopN: 1 });
    expect(result.lines[0]!.unit_price).toBe(22);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["safe"]);
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

  it("checks ranges only for admitted candidates, not rejected or unscreened exact matches", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "outside", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "bracket", part_no: "AB-123", quantity: 100, unit_price: 9 }),
      row({ quote_no: "bracket", part_no: "AB-123", quantity: 200, unit_price: 7 }),
      row({ quote_no: "skipped", part_no: "AB-123", quantity: 150, unit_price: 8 }),
    ]);
    const jev = {
      enabled: false,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => ({
        rankedIds: ["outside", "bracket", "skipped"], probabilities: {}, source: "jev" as const,
      }),
      screenCandidate: async (_part: unknown, c: Candidate) =>
        c.row.quote_no === "outside" ? "admit" as const : "reject" as const,
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["outside"]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 150 }] },
      { jev, rankLimit: 3, screenTopN: 2 });
    expect(result.lines[0]!.unit_price).toBe(20);
    expect(result.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["outside"]);
    expect(result.lines[0]!.warnings).toContain("rejected analog bracket");
    expect(result.lines[0]!.warnings).toContain("screening budget skipped 1 analog");
    expect(result.lines[0]!.warnings).toContain("requested quantity outside all usable analog price-break ranges — manual review needed");
  });

  it("holds when exact candidates are quarantined without pricing from other history", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "exact", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "fuzzy", part_no: "AB-124", quantity: 10, unit_price: 30 }),
    ]);
    const jev = {
      enabled: false,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["exact"]);
        return { rankedIds: ["exact"], probabilities: {}, source: "fallback" as const };
      },
      screenCandidate: async () => "quarantine" as const,
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates).toEqual([]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 100 }] }, { jev });
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.analogs).toEqual([]);
    expect(result.lines[0]!.warnings).toContain("quarantined analog exact");
    expect(result.lines[0]!.warnings).not.toContain("requested quantity outside all usable analog price-break ranges — manual review needed");
  });

  it("retains the highest-ranked usable candidate as a Jev provisional fallback", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "weak", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "stronger", part_no: "AB-123", quantity: 10, unit_price: 30 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({
        rankedIds: ["weak", "stronger"], probabilities: {}, source: "jev" as const,
      }),
      screenCandidate: async () => "reject" as const,
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["weak"]);
        return "median_won" as const;
      },
    } as unknown as JevClient;

    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 10 }] }, { jev });
    const line = result.lines[0]!;
    expect(line.unit_price).toBe(20);
    expect(line.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(line.evidence_status).toBe("HISTORICAL_INTERNAL_CALCULATION");
    expect(line.analogs.map((a) => a.quote_no)).toEqual(["weak"]);
    expect(line.warnings).toContain(
      "Jev admitted no high-confidence analog; retained highest-ranked usable candidate weak as a provisional human-review fallback",
    );
    expect(line.uncertainties).toContain(
      "Jev admitted no high-confidence analog; retained candidate is a provisional human-review fallback",
    );
  });

  it("keeps the estimate missing when Jev admits nothing and no usable break exists", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unpriced", part_no: "AB-123", quantity: 0, unit_price: 0 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({
        rankedIds: ["unpriced"], probabilities: {}, source: "jev" as const,
      }),
      screenCandidate: async () => "quarantine" as const,
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;

    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 10 }] }, { jev });
    const line = result.lines[0]!;
    expect(line.unit_price).toBeNull();
    expect(line.proposal_status).toBe("MISSING");
    expect(line.evidence_status).toBe("PRESENT_BUT_NO_USABLE_PRICE");
    expect(line.analogs).toEqual([]);
    expect(line.warnings).not.toContain(expect.stringContaining("provisional human-review fallback"));
  });

  it("holds when screening is disabled even if Jev is enabled and historical prices exist", async () => {
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({ rankedIds: ["priced"], probabilities: {}, source: "jev" as const }),
      screenCandidate: async () => { throw new Error("screening must remain disabled"); },
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates).toEqual([]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const register = new QuoteRegister([row({ quote_no: "priced", part_no: "SYN-1", quantity: 10, unit_price: 25 })]);
    const result = await estimate(register, { parts: [{ part_no: "SYN-1", quantity: 10 }] }, { jev, screenTopN: 0 });
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.proposal_status).toBe("MISSING");
    expect(result.lines[0]!.analogs).toEqual([]);
    expect(result.lines[0]!.warnings.some((w) => w.includes("provisional human-review fallback"))).toBe(false);
  });

  it("does not fall back to an unscreened priced candidate beyond the screening budget", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "unpriced", part_no: "SYN-1", description: "BRACKET", quantity: 10, unit_price: 0 }),
      row({ quote_no: "unscreened", part_no: "SYN-2", description: "BRACKET", quantity: 10, unit_price: 25 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({ rankedIds: ["unpriced", "unscreened"], probabilities: {}, source: "jev" as const }),
      screenCandidate: async (_part: unknown, c: Candidate) => {
        expect(c.row.quote_no).toBe("unpriced");
        return "quarantine" as const;
      },
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates).toEqual([]);
        return "median_won" as const;
      },
    } as unknown as JevClient;
    const result = await estimate(register, { parts: [{ description: "BRACKET", quantity: 10 }] }, { jev, screenTopN: 1 });
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.analogs).toEqual([]);
    expect(result.lines[0]!.warnings).toContain("screening budget skipped 1 analog");
  });

  it("does not use a provisional fallback when Jev admits a candidate", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "rejected", part_no: "AB-123", quantity: 10, unit_price: 20 }),
      row({ quote_no: "admitted", part_no: "AB-123", quantity: 10, unit_price: 30 }),
    ]);
    const jev = {
      enabled: true,
      rankAnalogs: async () => ({
        rankedIds: ["rejected", "admitted"], probabilities: {}, source: "jev" as const,
      }),
      screenCandidate: async (_part: unknown, c: Candidate) =>
        c.row.quote_no === "admitted" ? "admit" as const : "reject" as const,
      chooseStrategy: async (_part: unknown, candidates: Candidate[]) => {
        expect(candidates.map((c) => c.row.quote_no)).toEqual(["admitted"]);
        return "median_won" as const;
      },
    } as unknown as JevClient;

    const result = await estimate(register, { parts: [{ part_no: "AB-123", quantity: 10 }] }, { jev });
    const line = result.lines[0]!;
    expect(line.unit_price).toBe(30);
    expect(line.analogs.map((a) => a.quote_no)).toEqual(["admitted"]);
    expect(line.warnings).not.toContain(expect.stringContaining("provisional human-review fallback"));
  });
});
