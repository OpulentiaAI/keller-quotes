import type { Candidate, PricePoint } from "./types.js";
import { normalizeCustomer } from "./register.js";

const DAY = 86_400_000;

function recencyWeight(dateStr: string, now = Date.now()): number {
  const t = Date.parse(dateStr);
  if (Number.isNaN(t)) return 0.3;
  const years = Math.max(0, (now - t) / (365 * DAY));
  return Math.exp(-years / 8); // ~8y half-life-ish decay
}

/** Interpolate (or near-extrapolate) unit price at targetQty from one quote's breaks. */
export function interpolateAtQty(breaks: { quantity: number | null; unit_price: number | null }[], targetQty: number): number | null {
  const byQuantity = new Map<number, number[]>();
  for (const b of breaks) {
    if (b.quantity === null || b.unit_price === null || !Number.isFinite(b.quantity) ||
      !Number.isFinite(b.unit_price) || b.quantity <= 0 || b.unit_price <= 0) continue;
    const prices = byQuantity.get(b.quantity) ?? [];
    prices.push(b.unit_price);
    byQuantity.set(b.quantity, prices);
  }
  const pts = [...byQuantity].map(([q, prices]) => ({
    q, p: prices.every((value) => value === prices[0]) ? prices[0]! :
      Math.exp(prices.reduce((sum, value) => sum + Math.log(value), 0) / prices.length),
  })).sort((a, b) => a.q - b.q);
  if (!pts.length) return null;
  const first = pts[0]!;
  const last = pts[pts.length - 1]!;
  if (pts.length === 1) return first.p;
  // find bracketing points in log space
  if (targetQty <= first.q) {
    // mild power-law extrapolation below the smallest break, damped
    const b = pts[1]!;
    const slope = Math.log(b.p / first.p) / Math.log(b.q / first.q);
    const est = first.p * Math.pow(targetQty / first.q, slope);
    // never extrapolate more than 25% above the smallest-break price
    return Math.min(est, first.p * 1.25);
  }
  if (targetQty >= last.q) {
    const a = pts[pts.length - 2]!;
    const slope = Math.log(last.p / a.p) / Math.log(last.q / a.q);
    const est = last.p * Math.pow(targetQty / last.q, slope);
    return Math.max(est, last.p * 0.7); // damp extrapolation below largest break
  }
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i]!;
    const b = pts[i + 1]!;
    if (targetQty >= a.q && targetQty <= b.q) {
      const t = (Math.log(targetQty) - Math.log(a.q)) / (Math.log(b.q) - Math.log(a.q));
      return Math.exp(Math.log(a.p) + t * (Math.log(b.p) - Math.log(a.p)));
    }
  }
  return null;
}

function weightedQuantile(items: { v: number; w: number }[], q: number): number | null {
  const sorted = items.filter((i) => i.w > 0).sort((a, b) => a.v - b.v);
  const total = sorted.reduce((s, i) => s + i.w, 0);
  if (!sorted.length || total <= 0) return null;
  let acc = 0;
  for (const i of sorted) {
    acc += i.w;
    if (acc / total >= q) return i.v;
  }
  return sorted[sorted.length - 1]!.v;
}

export interface PriceResult {
  unit_price: number | null;
  low: number | null;
  high: number | null;
  confidence: number;
  method: string;
  points: PricePoint[];
}

export function price(
  targetQty: number,
  candidates: Candidate[],
  opts: {
    strategy: "latest" | "median_won" | "curve_fit" | "conservative";
    jevProbabilities?: Record<string, number>;
    customerId?: string;
    customer?: string;
    now?: number;
  },
): PriceResult {
  const now = opts.now ?? Date.now();
  const points: PricePoint[] = [];
  const regression: { quantity: number; unit_price: number; weight: number }[] = [];
  for (const c of candidates) {
    const p = interpolateAtQty(c.breaks, targetQty);
    if (p === null) continue;
    let w = c.score * recencyWeight(c.row.quote_date, now);
    const jevP = opts.jevProbabilities?.[c.row.quote_no];
    if (jevP !== undefined) w *= 0.25 + jevP;
    if (c.row.status === "won") w *= 1.25;
    if (opts.customerId ? c.row.customer_id === opts.customerId :
      opts.customer && c.row.customer && normalizeCustomer(c.row.customer) === normalizeCustomer(opts.customer)) w *= 1.2;
    const byQuantity = new Map<number, number[]>();
    for (const b of c.breaks) {
      if (b.quantity === null || b.unit_price === null || !Number.isFinite(b.quantity) ||
        !Number.isFinite(b.unit_price) || b.quantity <= 0 || b.unit_price <= 0) continue;
      const prices = byQuantity.get(b.quantity) ?? [];
      prices.push(b.unit_price);
      byQuantity.set(b.quantity, prices);
    }
    for (const [quantity, prices] of byQuantity) regression.push({ quantity,
      unit_price: prices.every((value) => value === prices[0]) ? prices[0]! :
        Math.exp(prices.reduce((sum, value) => sum + Math.log(value), 0) / prices.length),
      weight: w / byQuantity.size });
    points.push({
      quantity: targetQty,
      unit_price: p,
      quote_no: c.row.quote_no,
      quote_date: c.row.quote_date,
      status: c.row.status,
      weight: w,
    });
  }
  if (!points.length) {
    return { unit_price: null, low: null, high: null, confidence: 0, method: "no_analogs", points };
  }

  let unit: number | null = null;
  let method = opts.strategy;
  if (opts.strategy === "latest" || points.length === 1) {
    const latest = [...points].sort((a, b) => b.quote_date.localeCompare(a.quote_date))[0]!;
    unit = latest.unit_price;
    method = "latest";
  } else if (opts.strategy === "curve_fit" && regression.length >= 3) {
    // pooled log-log regression, weighted
    let sw = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (const pt of regression) {
      const x = Math.log(pt.quantity);
      const y = Math.log(pt.unit_price);
      sw += pt.weight;
      sx += pt.weight * x;
      sy += pt.weight * y;
      sxx += pt.weight * x * x;
      sxy += pt.weight * x * y;
    }
    const denom = sw * sxx - sx * sx;
    if (Math.abs(denom) < 1e-9) {
      unit = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.5);
      method = "median_won";
    } else {
      const slope = (sw * sxy - sx * sy) / denom;
      const intercept = (sy - slope * sx) / sw;
      const est = Math.exp(intercept + slope * Math.log(targetQty));
      const med = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.5);
      // guard against absurd slopes from quantity-scattered analogs
      unit = med !== null && (est > med * 2.5 || est < med / 2.5) ? med : est;
      method = unit === med ? "median_won" : "curve_fit";
    }
  } else if (opts.strategy === "conservative") {
    unit = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.75);
  } else {
    unit = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.5);
    method = "median_won";
  }

  const low = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.25);
  const high = weightedQuantile(points.map((p) => ({ v: p.unit_price, w: p.weight })), 0.75);

  // Confidence: analog count, score mass, price agreement, recency.
  const n = points.length;
  const spread = low && high && unit ? (high - low) / unit : 1;
  const maxDate = Math.max(...points.map((p) => Date.parse(p.quote_date) || 0));
  const ageYears = (now - maxDate) / (365 * DAY);
  const conf = Math.max(
    0.05,
    Math.min(
      0.95,
      0.25 +
        Math.min(0.3, n * 0.04) +
        Math.min(0.2, Math.max(...points.map((p) => p.weight)) * 0.2) +
        (spread < 0.3 ? 0.15 : spread < 0.7 ? 0.08 : 0) +
        (ageYears < 2 ? 0.05 : 0) -
        Math.min(0.3, Math.max(0, ageYears - 5) * 0.05),
    ),
  );

  return { unit_price: unit, low, high, confidence: Math.round(conf * 100) / 100, method, points };
}
