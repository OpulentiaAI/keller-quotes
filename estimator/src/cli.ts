#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";
import { QuoteRegister } from "./register.js";
import { estimate } from "./estimate.js";
import type { EstimateRequest, QuoteEstimate } from "./types.js";

function usage(): never {
  console.error(`usage: estimate <request.json> [--register quotes.csv] [--csv out.csv] [--offline]

request.json:
{
  "customer": "ACME MFG",            // optional, boosts same-customer analogs
  "customer_id": "000317",           // optional FabriTRAK COMP_ID
  "rfq_no": "RFQ-123",
  "parts": [
    {
      "part_no": "96-0085-00",       // optional if description given
      "description": "RETAINER PLATE",
      "quantity": 250,
      "material": "S.S 304",          // optional
      "drawing_ref": "RAL-0214"       // optional drawing/visualization reference
    }
  ]
}

env: AI_GATEWAY_API_KEY enables Jev ranking/screening/strategy (typesafe-ai/jev).
     --offline forces the deterministic fallback path.`);
  process.exit(2);
}

const argv = process.argv.slice(2);
const reqPath = argv[0];
if (!reqPath || reqPath.startsWith("--")) usage();
const flag = (n: string) => argv.includes(n);
const opt = (n: string) => {
  const i = argv.indexOf(n);
  return i >= 0 ? argv[i + 1] : undefined;
};

const registerPath =
  opt("--register") ?? process.env.KELLER_REGISTER ?? "data/quotes.csv";
const offline = flag("--offline");

const req = JSON.parse(readFileSync(reqPath, "utf8")) as EstimateRequest;
if (!Array.isArray(req.parts) || !req.parts.length) {
  console.error("request.parts must be a nonempty array");
  process.exit(2);
}
for (const p of req.parts) {
  if (!p.quantity || p.quantity <= 0) {
    console.error(`part ${p.part_no ?? p.description ?? "?"}: quantity must be > 0`);
    process.exit(2);
  }
}

const reg = QuoteRegister.fromCsv(registerPath);
if (offline) delete process.env.AI_GATEWAY_API_KEY;

const result: QuoteEstimate = await estimate(reg, req);
console.log(JSON.stringify(result, null, 2));

const csvPath = opt("--csv");
if (csvPath) {
  const header = "part_no,description,quantity,unit_price,extended_price,price_low,price_high,confidence,method,top_analog_quote,top_analog_date,top_analog_status,warnings\n";
  const esc = (s: unknown) => {
    const v = s === null || s === undefined ? "" : String(s);
    return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  };
  const body = result.lines
    .map((l) =>
      [
        l.part.part_no, l.part.description, l.part.quantity, l.unit_price,
        l.extended_price, l.price_low, l.price_high, l.confidence, l.method,
        l.analogs[0]?.quote_no, l.analogs[0]?.quote_date, l.analogs[0]?.status,
        l.warnings.join("; "),
      ].map(esc).join(","),
    )
    .join("\n");
  writeFileSync(csvPath, header + body + "\n");
  console.error(`wrote ${csvPath}`);
}
