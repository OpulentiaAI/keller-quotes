#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { QuoteRegister } from "./register.js";
import { assertEstimateRequest, estimate } from "./estimate.js";
import type { QuoteEstimate } from "./types.js";

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

const sourceData = new URL("../data/quotes.csv", import.meta.url);
const registerPath = opt("--register") ?? process.env.KELLER_REGISTER ?? fileURLToPath(
  existsSync(sourceData) ? sourceData : new URL("../../data/quotes.csv", import.meta.url),
);
const offline = flag("--offline");

let req: unknown;
try {
  req = JSON.parse(readFileSync(reqPath, "utf8"));
  assertEstimateRequest(req);
} catch (error) {
  console.error(`invalid request: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(2);
}

const reg = QuoteRegister.fromCsv(registerPath);
if (offline) delete process.env.AI_GATEWAY_API_KEY;

const result: QuoteEstimate = await estimate(reg, req);
console.log(JSON.stringify(result, null, 2));

const csvPath = opt("--csv");
if (csvPath) {
  const header = "part_no,description,quantity,unit_price,extended_price,price_low,price_high,confidence,method,top_analog_quote,top_analog_date,top_analog_status,warnings\n";
  const esc = (s: unknown) => {
    let v = s === null || s === undefined ? "" : String(s);
    if (typeof s === "string" && /^[\s\x00-\x1f]*[=+\-@]/.test(s)) v = `'${v}`;
    return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
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
