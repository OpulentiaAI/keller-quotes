import { createGateway } from "@ai-sdk/gateway";
import { experimental_evaluate } from "ai";
import type { Candidate, JevVerdict, PartRequest } from "./types.js";

const JEV_MODEL_ID = "typesafe-ai/jev" as const;
const TIMEOUT_MS = 15_000;

function describePart(p: PartRequest): Record<string, string | number | null> {
  return {
    part_no: p.part_no ?? null,
    description: p.description ?? null,
    quantity: p.quantity,
    material: p.material ?? null,
    finish: p.finish ?? null,
    notes: p.notes ?? null,
  };
}

function describeCandidate(id: string, c: Candidate): string {
  const r = c.row;
  return [
    `quote ${r.quote_no} (${r.quote_date})`,
    `part ${r.part_no}`,
    r.description,
    r.customer ? `for ${r.customer.trim()}` : "",
    r.material ? `material ${r.material}` : "",
    `status ${r.status}`,
    `breaks: ${c.breaks
      .filter((b) => b.quantity && b.unit_price)
      .map((b) => `${b.quantity}@$${b.unit_price}`)
      .join(", ")}`,
  ]
    .filter(Boolean)
    .join(" | ");
}

export class JevClient {
  private model: ReturnType<ReturnType<typeof createGateway>["evaluationModel"]> | null;

  constructor(apiKey = process.env.AI_GATEWAY_API_KEY) {
    this.model = apiKey
      ? createGateway({ apiKey }).evaluationModel(JEV_MODEL_ID)
      : null;
  }

  get enabled(): boolean {
    return this.model !== null;
  }

  /**
   * Rank candidate analogs for a part request. Jev answers a bounded choice
   * over at most `max` candidates; probabilities (if returned) order the rest.
   * Falls back to deterministic score order when Jev is unavailable or fails.
   */
  async rankAnalogs(part: PartRequest, candidates: Candidate[], max = 8): Promise<JevVerdict> {
    const top = candidates.slice(0, max);
    if (!this.model || top.length === 0) {
      return this.fallback(candidates);
    }
    const criteria: Record<string, string> = {};
    top.forEach((c, i) => {
      criteria[`c${i}`] = describeCandidate(`c${i}`, c);
    });
    try {
      const res = await experimental_evaluate({
        model: this.model,
        state: {
          task: "Select the historical quote that is the best pricing analog for the requested part. Prefer identical part numbers, then matching material/process, same customer, and quantities near the requested quantity.",
          requested_part: describePart(part),
        },
        questions: {
          best_analog: { type: "choice", instructions: "Best pricing analog", criteria },
        },
        maxRetries: 0,
        abortSignal: AbortSignal.timeout(TIMEOUT_MS),
      });
      const ans = res.answers.best_analog;
      if (ans.type !== "choice") return this.fallback(candidates);
      const probs = ans.probabilities ?? {};
      const ordered = Object.keys(criteria).sort(
        (a, b) => (probs[b] ?? (a === ans.choice ? 1 : 0)) - (probs[a] ?? (b === ans.choice ? 1 : 0)),
      );
      // Merge Jev order for the top-K with deterministic order for the tail.
      const byId = new Map(top.map((c, i) => [`c${i}`, c]));
      const ranked: Candidate[] = ordered.map((id) => byId.get(id)!).filter(Boolean);
      for (const c of candidates) if (!ranked.includes(c)) ranked.push(c);
      const probabilities: Record<string, number> = {};
      for (const [id, p] of Object.entries(probs)) {
        const c = byId.get(id);
        if (c) probabilities[c.row.quote_no] = p;
      }
      return { rankedIds: ranked.map((c) => c.row.quote_no), probabilities, source: "jev" };
    } catch {
      return this.fallback(candidates);
    }
  }

  /** Screen one candidate for analog validity (injection- and nonsense-safe). */
  async screenCandidate(part: PartRequest, c: Candidate): Promise<"admit" | "quarantine" | "reject"> {
    if (!this.model) return c.score >= 0.3 ? "admit" : "quarantine";
    try {
      const res = await experimental_evaluate({
        model: this.model,
        state: {
          task: "Decide whether the historical quote is a genuine pricing analog for the requested part (same or closely related part/material/process), not an unrelated record.",
          requested_part: describePart(part),
          candidate: describeCandidate(c.row.quote_no, c),
        },
        questions: {
          is_analog: { type: "boolean", instructions: "Candidate is a genuine pricing analog" },
        },
        maxRetries: 0,
        abortSignal: AbortSignal.timeout(TIMEOUT_MS),
      });
      const ans = res.answers.is_analog;
      if (ans.type !== "boolean") return "quarantine";
      return ans.probability >= 0.7 ? "admit" : ans.probability >= 0.4 ? "quarantine" : "reject";
    } catch {
      return "quarantine";
    }
  }

  /**
   * Bounded choice over pricing strategies for a part line. Jev picks; the
   * estimator only executes the returned canonical strategy id.
   */
  async chooseStrategy(
    part: PartRequest,
    candidates: Candidate[],
  ): Promise<"latest" | "median_won" | "curve_fit" | "conservative"> {
    const fallback = "median_won";
    if (!this.model || candidates.length === 0) return fallback;
    try {
      const res = await experimental_evaluate({
        model: this.model,
        state: {
          task: "Choose the pricing strategy for this part line from the historical analogs.",
          requested_part: describePart(part),
          analog_count: candidates.length,
          won_count: candidates.filter((c) => c.row.status === "won").length,
          exact_part_match: candidates.some((c) => c.reasons.includes("exact part_no")),
        },
        questions: {
          strategy: {
            type: "choice",
            instructions: "Pricing strategy",
            criteria: {
              latest: "Use the most recent matching quote's price curve.",
              median_won: "Weighted median of interpolated prices, preferring won quotes.",
              curve_fit: "Log-log regression across analog qty/price breaks.",
              conservative: "Upper-quartile price when evidence is thin or conflicting.",
            },
          },
        },
        maxRetries: 0,
        abortSignal: AbortSignal.timeout(TIMEOUT_MS),
      });
      const ans = res.answers.strategy;
      if (ans.type !== "choice") return fallback;
      const ok = ["latest", "median_won", "curve_fit", "conservative"] as const;
      return (ok as readonly string[]).includes(ans.choice) ? (ans.choice as (typeof ok)[number]) : fallback;
    } catch {
      return fallback;
    }
  }

  private fallback(candidates: Candidate[]): JevVerdict {
    return { rankedIds: candidates.map((c) => c.row.quote_no), probabilities: {}, source: "fallback" };
  }
}
