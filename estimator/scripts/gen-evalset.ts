// Generate evals/evalset.jsonl from the register: historical quote lines whose
// actual quoted unit price is known, so the estimator's prediction can be
// scored leave-one-out (the source quote is excluded from its own analogs).
import { writeFileSync, mkdirSync } from "node:fs";
import { QuoteRegister } from "../src/register.js";

const registerPath = process.argv[2] ?? "data/quotes.csv";
const outPath = process.argv[3] ?? "evals/evalset.jsonl";
const N = Number(process.argv[4] ?? 250);

const reg = QuoteRegister.fromCsv(registerPath);

interface Case {
  id: string;
  source_quote_no: string;
  input: {
    part_no?: string;
    description?: string;
    quantity: number;
    material?: string;
    customer?: string;
    customer_id?: string;
  };
  actual_unit_price: number;
  actual_quantity: number;
  quote_date: string;
  status: string;
}

const cases: Case[] = [];
for (const g of reg.groups) {
  const priced = g.breaks.filter((b) => b.unit_price && b.unit_price > 0 && b.quantity && b.quantity > 0);
  if (!priced.length) continue;
  // pick the break nearest the median quantity — most "typical" order size
  const mid = priced[Math.floor(priced.length / 2)]!;
  if (!g.head.part_no && !g.head.description) continue;
  cases.push({
    id: `${g.quote_no}@${mid.quantity}`,
    source_quote_no: g.quote_no.split("|")[0]!,
    input: {
      part_no: g.head.part_no || undefined,
      description: g.head.description || undefined,
      quantity: mid.quantity!,
      material: g.head.material || undefined,
      customer: g.head.customer.trim() || undefined,
      customer_id: g.head.customer_id || undefined,
    },
    actual_unit_price: mid.unit_price!,
    actual_quantity: mid.quantity!,
    quote_date: g.head.quote_date,
    status: g.head.status,
  });
}

// Stratified shuffle: deterministic seed, oversample won + recent + multi-break
// quotes (richest signal), then cap.
let seed = 42;
const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const score = (c: (typeof cases)[0]) =>
  (c.status === "won" ? 2 : 1) * (1 + Math.min(1, Number.parseInt(c.quote_date.slice(0, 4)) > 2015 ? 1 : 0));
const pool = cases
  .map((c) => ({ c, k: rand() * score(c) }))
  .sort((a, b) => b.k - a.k)
  .map((x) => x.c)
  .slice(0, N)
  .sort((a, b) => a.quote_date.localeCompare(b.quote_date));

mkdirSync(outPath.split("/").slice(0, -1).join("/") || ".", { recursive: true });
writeFileSync(outPath, pool.map((c) => JSON.stringify(c)).join("\n") + "\n");
console.log(`wrote ${pool.length} cases to ${outPath}`);
console.log(`won: ${pool.filter((c) => c.status === "won").length}, open: ${pool.filter((c) => c.status !== "won").length}`);
console.log(`date range: ${pool[0]?.quote_date} .. ${pool[pool.length - 1]?.quote_date}`);
