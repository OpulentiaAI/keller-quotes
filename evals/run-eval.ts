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
const retrospective = argv.includes("--retrospective");
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
  .split("\n")
  .filter((line) => line.trim())
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
  status: "priced" | "no_analog" | "unreplayable";
}

const results: Result[] = [];
for (const [i, c] of cases.entries()) {
  if (!Number.isFinite(c.actual_unit_price) || c.actual_unit_price <= 0 ||
    !Number.isFinite(c.input.quantity) || c.input.quantity <= 0 ||
    (!retrospective && (!/^\d{4}-\d{2}-\d{2}$/.test(c.quote_date) ||
    Number.isNaN(Date.parse(`${c.quote_date}T00:00:00Z`)) ||
    new Date(`${c.quote_date}T00:00:00Z`).toISOString().slice(0, 10) !== c.quote_date))) {
    results.push({ id: c.id, actual: c.actual_unit_price, predicted: null, ape: null,
      confidence: 0, method: "unreplayable", basis: "missing/invalid quote date, price, or quantity", analogs: 0, status: "unreplayable" });
    continue;
  }
  const res = await estimate(
    reg,
    {
      customer: retrospective ? c.input.customer : undefined,
      customer_id: c.input.customer_id,
      parts: [
        {
          part_no: c.input.part_no,
          description: c.input.description,
          quantity: c.input.quantity,
          material: retrospective ? c.input.material : undefined,
        },
      ],
    },
    { jev, exclude: new Set([c.source_quote_no]), asOf: retrospective ? undefined : c.quote_date },
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
    status: l.unit_price === null ? "no_analog" : "priced",
  });
  if ((i + 1) % 25 === 0) console.error(`…${i + 1}/${cases.length}`);
}

const priced = results.filter((r): r is Result & { ape: number } => r.ape !== null);
const apes = priced.map((r) => r.ape!).sort((a, b) => a - b);
const median = (xs: number[]) => (xs.length ? xs[Math.floor(xs.length / 2)]! : null);
const pctWithin = (t: number) => priced.length ? (priced.filter((r) => r.ape! <= t).length / priced.length) * 100 : null;
const worst = [...priced].sort((a, b) => b.ape! - a.ape!).slice(0, 10);

const summary = {
  mode: retrospective ? "retrospective leave-one-out (future data visible)" : "cutoff-aware frozen-snapshot replay (not a true backtest)",
  cases: results.length,
  priced: priced.length,
  no_analog: results.filter((r) => r.status === "no_analog").length,
  unreplayable: results.filter((r) => r.status === "unreplayable").length,
  coverage: results.length ? priced.length / results.length : null,
  median_ape: median(apes),
  mean_ape: apes.length ? apes.reduce((s, x) => s + x, 0) / apes.length : null,
  within_10pct: pctWithin(0.1),
  within_20pct: pctWithin(0.2),
  within_50pct: pctWithin(0.5),
  mean_confidence: results.length ? results.reduce((s, r) => s + r.confidence, 0) / results.length : null,
  jev: useJev,
};

const md = [
  `# Estimator eval — ${summary.mode} — ${new Date().toISOString()}`,
  "",
  `register: \`${registerPath}\` (${reg.rowCount} rows) · evalset: \`${evalsetPath}\` · jev: ${useJev ? "on" : "off"}`,
  "",
  retrospective ? "Retrospective mode exposes later quotes and outcomes; its accuracy is not quote-time accuracy." :
    "A quote-time cutoff excludes same-day/future quotes and later-dated revisions/letters, and hides wins dated after the cutoff. Earlier records can contain unversioned edits from later dates, so the frozen extract cannot prove a true historical backtest. The fixed evalset intentionally oversamples won and recent quotes; results do not represent natural quote prevalence.",
  "",
  "| metric | value |",
  "|---|---|",
  `| cases | ${summary.cases} |`,
  `| priced | ${summary.priced} |`,
  `| no analog | ${summary.no_analog} |`,
  `| unreplayable | ${summary.unreplayable} |`,
  `| coverage (priced / all cases) | ${summary.coverage === null ? "n/a" : (summary.coverage * 100).toFixed(1) + "%"} |`,
  `| median APE | ${summary.median_ape === null ? "n/a" : (summary.median_ape * 100).toFixed(1) + "%"} |`,
  `| mean APE | ${summary.mean_ape === null ? "n/a" : (summary.mean_ape * 100).toFixed(1) + "%"} |`,
  `| within ±10% | ${summary.within_10pct === null ? "n/a" : summary.within_10pct.toFixed(1) + "%"} |`,
  `| within ±20% | ${summary.within_20pct === null ? "n/a" : summary.within_20pct.toFixed(1) + "%"} |`,
  `| within ±50% | ${summary.within_50pct === null ? "n/a" : summary.within_50pct.toFixed(1) + "%"} |`,
  `| mean confidence | ${summary.mean_confidence === null ? "n/a" : summary.mean_confidence.toFixed(2)} |`,
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
