// Leave-one-out evaluation: replay each eval case as a pricing request with the
// source quote excluded, then score predicted unit price vs the actual quote.
//
//   tsx evals/run-eval.ts [evalset.jsonl] [--register quotes.csv] [--jev] [--limit N] [--report out.md]
import { readFileSync, writeFileSync } from "node:fs";
import { QuoteRegister } from "../estimator/src/register.js";
import { estimate } from "../estimator/src/estimate.js";
import { JevClient } from "../estimator/src/jev.js";

const argv = process.argv.slice(2);
const VALUE_FLAGS = new Set(["--register", "--limit", "--report"]);
const positional: string[] = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i]!;
  if (VALUE_FLAGS.has(a)) {
    i++; // skip the flag's value
  } else if (!a.startsWith("--")) {
    positional.push(a);
  }
}
const opt = (n: string) => {
  const i = argv.indexOf(n);
  return i >= 0 ? argv[i + 1] : undefined;
};
const evalsetPath = positional[0] ?? "evals/evalset.jsonl";
const registerPath = opt("--register") ?? "quotes.csv";
const useJev = argv.includes("--jev");
const limit = Number(opt("--limit") ?? Infinity);
const reportPath = opt("--report") ?? `evals/report-${new Date().toISOString().slice(0, 10)}.md`;

interface EvalCase {
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
  quote_date: string;
  status: string;
}

const cases = readFileSync(evalsetPath, "utf8")
  .trim()
  .split("\n")
  .map((l) => JSON.parse(l) as EvalCase)
  .slice(0, limit);

const reg = QuoteRegister.fromCsv(registerPath);
const jev = useJev ? new JevClient() : new JevClient("");

interface Result {
  id: string;
  actual: number;
  predicted: number | null;
  ape: number | null; // absolute % error
  confidence: number;
  method: string;
  basis: string;
  analogs: number;
}

const results: Result[] = [];
for (const [i, c] of cases.entries()) {
  const res = await estimate(
    reg,
    {
      customer: c.input.customer,
      customer_id: c.input.customer_id,
      parts: [
        {
          part_no: c.input.part_no,
          description: c.input.description,
          quantity: c.input.quantity,
          material: c.input.material,
        },
      ],
    },
    { jev, exclude: new Set([c.source_quote_no]) },
  );
  const l = res.lines[0]!;
  const ape =
    l.unit_price !== null && c.actual_unit_price > 0
      ? Math.abs(l.unit_price - c.actual_unit_price) / c.actual_unit_price
      : null;
  results.push({
    id: c.id,
    actual: c.actual_unit_price,
    predicted: l.unit_price,
    ape,
    confidence: l.confidence,
    method: l.method,
    basis: l.status_basis,
    analogs: l.analogs.length,
  });
  if ((i + 1) % 25 === 0) console.error(`…${i + 1}/${cases.length}`);
}

const priced = results.filter((r) => r.predicted !== null) as (Result & { ape: number })[];
const apes = priced.map((r) => r.ape!).sort((a, b) => a - b);
const median = (xs: number[]) => (xs.length ? xs[Math.floor(xs.length / 2)]! : NaN);
const pctWithin = (t: number) => (priced.filter((r) => r.ape! <= t).length / Math.max(1, priced.length)) * 100;
const worst = [...priced].sort((a, b) => b.ape! - a.ape!).slice(0, 10);

const summary = {
  cases: results.length,
  coverage: priced.length / results.length,
  median_ape: median(apes),
  mean_ape: apes.reduce((s, x) => s + x, 0) / Math.max(1, apes.length),
  within_10pct: pctWithin(0.1),
  within_20pct: pctWithin(0.2),
  within_50pct: pctWithin(0.5),
  mean_confidence: results.reduce((s, r) => s + r.confidence, 0) / results.length,
  jev: useJev,
};

const md = [
  `# Estimator eval — ${new Date().toISOString()}`,
  "",
  `register: \`${registerPath}\` (${reg.rowCount} rows) · evalset: \`${evalsetPath}\` · jev: ${useJev ? "on" : "off"}`,
  "",
  "| metric | value |",
  "|---|---|",
  `| cases | ${summary.cases} |`,
  `| coverage (priced) | ${(summary.coverage * 100).toFixed(1)}% |`,
  `| median APE | ${(summary.median_ape * 100).toFixed(1)}% |`,
  `| mean APE | ${(summary.mean_ape * 100).toFixed(1)}% |`,
  `| within ±10% | ${summary.within_10pct.toFixed(1)}% |`,
  `| within ±20% | ${summary.within_20pct.toFixed(1)}% |`,
  `| within ±50% | ${summary.within_50pct.toFixed(1)}% |`,
  `| mean confidence | ${summary.mean_confidence.toFixed(2)} |`,
  "",
  "## Worst misses",
  "",
  "| case | actual | predicted | APE | method | analogs |",
  "|---|---|---|---|---|---|",
  ...worst.map(
    (r) =>
      `| ${r.id} | $${r.actual.toFixed(4)} | $${r.predicted!.toFixed(4)} | ${(r.ape! * 100).toFixed(0)}% | ${r.method} | ${r.analogs} |`,
  ),
  "",
].join("\n");

writeFileSync(reportPath, md);
writeFileSync(reportPath.replace(/\.md$/, ".json"), JSON.stringify({ summary, results }, null, 2));
console.log(JSON.stringify(summary, null, 2));
console.log(`wrote ${reportPath}`);
