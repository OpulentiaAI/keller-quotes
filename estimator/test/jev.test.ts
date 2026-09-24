import { createGateway } from "@ai-sdk/gateway";
import { experimental_evaluate } from "ai";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JevClient } from "../src/jev.js";
import type { Candidate, QuoteRow } from "../src/types.js";

vi.mock("@ai-sdk/gateway", () => ({
  createGateway: vi.fn(() => ({ evaluationModel: vi.fn(() => ({})) })),
}));
vi.mock("ai", () => ({ experimental_evaluate: vi.fn() }));

const candidate = (quote_no: string): Candidate => ({
  row: {
    quote_no, quote_date: "2024-01-01", part_no: quote_no,
    description: "RETAINER PLATE", customer: "", material: "", status: "won",
  } as QuoteRow,
  breaks: [{ quantity: 10, unit_price: 5 } as QuoteRow],
  score: 0.8,
  reasons: [],
});

describe("Jev analog ranking", () => {
  beforeEach(() => vi.clearAllMocks());

  it("ranks the selected analog first when Jev omits probabilities", async () => {
    vi.mocked(experimental_evaluate).mockResolvedValue({
      answers: { best_analog: { type: "choice", choice: "c1" } },
    } as never);
    const verdict = await new JevClient("test-key").rankAnalogs(
      { part_no: "B", quantity: 10 },
      [candidate("A"), candidate("B"), candidate("C")],
    );

    expect(createGateway).toHaveBeenCalled();
    expect(experimental_evaluate).toHaveBeenCalledOnce();
    expect(verdict).toEqual({
      rankedIds: ["B", "A", "C"], probabilities: {}, source: "jev",
    });
  });

  it("uses each criterion's own probability when only some are provided", async () => {
    vi.mocked(experimental_evaluate).mockResolvedValue({
      answers: { best_analog: { type: "choice", choice: "c2", probabilities: { c0: 0.6 } } },
    } as never);
    const verdict = await new JevClient("test-key").rankAnalogs(
      { part_no: "C", quantity: 10 },
      [candidate("A"), candidate("B"), candidate("C")],
    );

    expect(verdict.rankedIds).toEqual(["C", "A", "B"]);
  });
});
