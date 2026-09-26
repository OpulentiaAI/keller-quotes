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
    expect(estimateOne.lines[0]!.analogs.map((a) => a.quote_no)).toEqual(["Q2", "Q3", "Q4"]);

    screenCandidate.mockClear();
    const estimateZero = await estimate(reg, req, { jev, screenTopN: 0 });
    expect(screenCandidate).not.toHaveBeenCalled();
    expect(estimateZero.lines[0]!.analogs).toHaveLength(4);
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
