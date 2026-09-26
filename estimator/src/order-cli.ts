#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { QuoteRegister } from "./register.js";
import { buildPricedOrder, renderOrderMarkdown } from "./order.js";

function usage(): never {
  throw new Error("usage: order-cli <request.json> [--register quotes.csv] --out NEW_DIRECTORY");
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  if (!args.length || args[0]!.startsWith("--")) usage();
  let registerPath: string | undefined;
  let outputPath: string | undefined;
  for (let i = 1; i < args.length; i += 2) {
    if (i + 1 >= args.length || args[i + 1]!.startsWith("--")) usage();
    if (args[i] === "--register" && registerPath === undefined) registerPath = args[i + 1];
    else if (args[i] === "--out" && outputPath === undefined) outputPath = args[i + 1];
    else usage();
  }
  if (!outputPath) usage();
  const sourceDefault = fileURLToPath(new URL("../../quotes.csv", import.meta.url));
  const compiledDefault = fileURLToPath(new URL("../../../quotes.csv", import.meta.url));
  const register = resolve(registerPath ?? (existsSync(sourceDefault) ? sourceDefault : compiledDefault));
  const out = resolve(outputPath);
  if (existsSync(out)) throw new Error(`output path already exists: ${out}`);
  if (out === resolve(args[0]!) || out === register) throw new Error("output path conflicts with an input");

  const request: unknown = JSON.parse(readFileSync(args[0]!, "utf8"));
  const digest = (file: string) => createHash("sha256").update(readFileSync(file)).digest("hex");
  const registerSha256 = digest(register);
  const reg = QuoteRegister.fromCsv(register);
  if (digest(register) !== registerSha256) throw new Error("register changed during parsing");
  const order = await buildPricedOrder(reg, request, { registerSha256 });
  const json = JSON.stringify(order, null, 2) + "\n";
  const markdown = renderOrderMarkdown(order);
  mkdirSync(out);
  try {
    writeFileSync(resolve(out, "order.json"), json, { flag: "wx" });
    writeFileSync(resolve(out, "order.md"), markdown, { flag: "wx" });
  } catch (error) {
    rmSync(out, { recursive: true, force: true });
    throw error;
  }
  console.log(JSON.stringify({ state: order.state, order_id: order.order_id, total: order.total, blockers: order.blockers, output_directory: out }));
  if (order.state === "BLOCKED") process.exitCode = 3;
}

main().catch((error: unknown) => {
  console.error(`invalid order: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 2;
});
