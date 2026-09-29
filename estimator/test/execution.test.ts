import { describe, expect, it, vi } from "vitest";
import { estimate } from "../src/estimate.js";
import type { JevClient } from "../src/jev.js";
import { QuoteRegister } from "../src/register.js";
import type { QuoteRow } from "../src/types.js";

const reg = new QuoteRegister(["Q1", "Q2", "Q3", "Q4"].map((quote_no) => ({
  quote_no, item_no: "", part_no: "PART-X", description: "RETAINER PLATE",
  quote_date: "2024-01-01", date_stamp: "", letter_date: "", customer_id: "",
  customer: "", material: "", comment: "", status: "open", won_date: "",
  drawing_no: "", quantity: 10, unit_price: 10,
}) as QuoteRow));
const req = { parts: [{ part_no: "PART-X", quantity: 10 }] };

describe("estimate execution limits", () => {
  it("screens only the first N visited candidates even when they are rejected", async () => {
    const screenCandidate = vi.fn(async () => "reject" as const);
    const jev = {
      enabled: false,
      rankAnalogs: vi.fn(async (_part: unknown, candidates: { row: QuoteRow }[]) => ({
        rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "fallback" as const,
      })),
      screenCandidate,
      chooseStrategy: vi.fn(async () => "median_won" as const),
    } as unknown as JevClient;

    const estimateOne = await estimate(reg, req, { jev, screenTopN: 1 });
    expect(screenCandidate).toHaveBeenCalledTimes(1);
    expect(estimateOne.lines[0]!.warnings).toContain("rejected analog Q1");
    expect(estimateOne.lines[0]!.unit_price).toBeNull();
    expect(estimateOne.lines[0]!.analogs).toEqual([]);
    expect(estimateOne.lines[0]!.proposal_status).toBe("MISSING");
    expect(estimateOne.lines[0]!.evidence_status).toBe("PRESENT_BUT_NO_USABLE_PRICE");

    screenCandidate.mockClear();
    const estimateZero = await estimate(reg, req, { jev, screenTopN: 0 });
    expect(screenCandidate).not.toHaveBeenCalled();
    expect(estimateZero.lines[0]!.unit_price).toBeNull();
    expect(estimateZero.lines[0]!.analogs).toEqual([]);
    expect(estimateZero.lines[0]!.evidence_status).toBe("PRESENT_BUT_NO_USABLE_PRICE");
    expect(estimateZero.lines[0]!.warnings).toContain("screening budget skipped 4 analogs");
  });

  it("quarantines uncertain analogs and never prices an unscreened tail", async () => {
    const screenCandidate = vi.fn(async (_part: unknown, c: { row: QuoteRow }) =>
      c.row.quote_no === "Q1" ? "quarantine" as const :
      c.row.quote_no === "Q2" ? "reject" as const : "admit" as const);
    const chooseStrategy = vi.fn(async (_part: unknown, _candidates: { row: QuoteRow }[]) => "median_won" as const);
    const jev = {
      enabled: false,
      rankAnalogs: vi.fn(async (_part: unknown, candidates: { row: QuoteRow }[]) => ({
        rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "fallback" as const,
      })),
      screenCandidate,
      chooseStrategy,
    } as unknown as JevClient;

    const line = (await estimate(reg, req, { jev, screenTopN: 3, rankLimit: 4 })).lines[0]!;
    expect(screenCandidate.mock.calls.map(([, c]) => c.row.quote_no)).toEqual(["Q1", "Q2", "Q3"]);
    expect(chooseStrategy.mock.calls[0]![1].map((c: { row: QuoteRow }) => c.row.quote_no)).toEqual(["Q3"]);
    expect(line.unit_price).toBe(10);
    expect(line.analogs.map((a) => a.quote_no)).toEqual(["Q3"]);
    expect(line.warnings).toContain("quarantined analog Q1");
    expect(line.warnings).toContain("rejected analog Q2");
    expect(line.warnings).toContain("screening budget skipped 1 analog");

    screenCandidate.mockClear();
    const bounded = (await estimate(reg, req, { jev, screenTopN: 8, rankLimit: 2 })).lines[0]!;
    expect(screenCandidate.mock.calls.map(([, c]) => c.row.quote_no)).toEqual(["Q1", "Q2"]);
    expect(bounded.unit_price).toBeNull();
    expect(bounded.analogs).toEqual([]);
    expect(bounded.evidence_status).toBe("PRESENT_BUT_NO_USABLE_PRICE");
  });

  it("exposes every admitted price candidate beyond five with source and date evidence", async () => {
    const many = new QuoteRegister(Array.from({ length: 8 }, (_, i) => ({
      quote_no: `Q${i + 1}`, item_no: "", part_no: "PART-X", description: "RETAINER PLATE",
      quote_date: i === 7 ? "2024-02-01" : "2024-01-01", date_stamp: i === 7 ? "2024-02-02" : "", customer_id: "",
      customer: "", material: "", comment: "", status: "open", won_date: "",
      drawing_no: "", quantity: 10, unit_price: i === 7 ? 80 : 10,
      quote_letter: `L${i + 1}`, letter_date: i === 7 ? "2024-02-01" : "2024-01-01", rev: i === 7 ? "B" : "",
      price_evidence: { price_basis: "internal_quote_calculation" },
    }) as QuoteRow));
    const jev = {
      enabled: false,
      rankAnalogs: vi.fn(async () => ({
        rankedIds: Array.from({ length: 8 }, (_, i) => `Q${i + 1}`),
        probabilities: {}, source: "jev" as const,
      })),
      screenCandidate: vi.fn(async () => "admit" as const),
      chooseStrategy: vi.fn(async () => "latest" as const),
    } as unknown as JevClient;

    const line = (await estimate(many, req, { jev, screenTopN: 8, rankLimit: 8 })).lines[0]!;
    expect(line.unit_price).toBe(80);
    expect(line.analogs.map((a) => a.quote_no)).toEqual(Array.from({ length: 8 }, (_, i) => `Q${i + 1}`));
    expect(line.analogs[7]).toMatchObject({
      quote_no: "Q8", quote_date: "2024-02-01", letter_date: "2024-02-01",
      date_stamp: "2024-02-02", rev: "B", quote_letter: "L8",
      price_evidence: { price_basis: "internal_quote_calculation" },
    });
  });

  it("rejects invalid limits before making any model calls", async () => {
    const rankAnalogs = vi.fn();
    const jev = { enabled: true, rankAnalogs } as unknown as JevClient;
    for (const bad of [-1, 0.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      await expect(estimate(reg, req, { jev, screenTopN: bad })).rejects.toThrow(/screenTopN/);
    }
    for (const bad of [-1, 0, 0.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      await expect(estimate(reg, req, { jev, rankLimit: bad })).rejects.toThrow(/rankLimit/);
    }
    expect(rankAnalogs).not.toHaveBeenCalled();
  });
});
