import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { retainIntake, verifyRetainedIntake } from "../src/intake.js";
import { assertOrderRequest, buildPricedOrder, requiresHistoricalRegister, type OrderRequest } from "../src/order.js";
import { QuoteRegister } from "../src/register.js";

const fixture = fileURLToPath(new URL("../examples/should-cost-intake.json", import.meta.url));
const root = fileURLToPath(new URL("../../", import.meta.url));
let home: string, oldHome: string | undefined;
let captured: string[];
beforeEach(() => { oldHome = process.env.HOME; home = mkdtempSync(join(tmpdir(), "synthetic-intake-")); process.env.HOME = home; captured = []; });
afterEach(() => {
  for (const dir of captured) chmodSync(dir, 0o700);
  rmSync(home, { recursive: true, force: true });
  if (oldHome === undefined) delete process.env.HOME; else process.env.HOME = oldHome;
});
function capture(requestPath = fixture) {
  expect(homedir()).toBe(home);
  const uploads = ["drawing", "worksheet"].map(id => {
    const path = join(home, `${id}.txt`); writeFileSync(path, `SYNTHETIC ${id}; not production evidence`);
    return { id, path, media_type: "text/plain" };
  });
  const result = retainIntake(requestPath, uploads, "Synthetic operator", assertOrderRequest);
  captured.push(result.directory);
  assertOrderRequest(result.request);
  return { ...result, request: result.request as unknown as OrderRequest };
}

function worksheet(request: OrderRequest) {
  const pricing = request.parts[0]!.pricing;
  if (pricing?.method !== "should_cost") throw new Error("synthetic fixture requires should_cost");
  return pricing.cost_basis;
}
const groups = ["components", "routing", "not_applicable"] as const;
function externalRequest(): OrderRequest {
  const request = JSON.parse(readFileSync(fixture, "utf8")) as OrderRequest;
  delete request.parts[0]!.source_evidence;
  delete request.parts[0]!.geometry;
  const basis = worksheet(request);
  for (const item of [...basis.components, ...basis.routing]) delete item.engineering_fact_ids;
  for (const group of groups) for (const item of basis[group]) for (const source of item.sources) {
    source.locator = "synthetic-external:reviewed-estimate#row=1";
    source.sha256 = createHash("sha256").update("SYNTHETIC external estimate").digest("hex");
  }
  return request;
}

describe("retained RFQ engineering intake and no-register production costing", () => {
  it("retains original bytes, units, field sources, cost worksheet and unknowns through 90 cost / 120 sell / 25% GM", async () => {
    const { request, directory } = capture();
    verifyRetainedIntake(request);
    expect(readFileSync(join(directory, "original-request.json"))).toEqual(readFileSync(fixture));
    expect(statSync(directory).mode & 0o777).toBe(0o500);
    for (const name of ["original-request.json", "request.json", "attachment-0.bin", "attachment-1.bin"]) expect(statSync(join(directory, name)).mode & 0o777).toBe(0o400);
    expect(requiresHistoricalRegister(request)).toBe(false);
    const order = await buildPricedOrder(new QuoteRegister([]), request, { registerSha256: null });
    expect(order.total).toBe(120);
    expect(order.lines[0]!.cost_breakdown!.estimated_line_cost.base).toBe(90);
    expect(order.lines[0]!.cost_breakdown!.estimated_line_margin_pct!.base).toBe(25);
    expect(order.lines[0]!.cost_breakdown!.supplied_basis).toEqual(worksheet(request));
    const attachment = request.intake!.attachments.find(a => a.id === "worksheet")!;
    for (const group of groups) for (const item of worksheet(request)[group]) {
      expect(item.sources[0]).toMatchObject({ sha256: attachment.sha256, locator: attachment.locator });
    }
    expect(order.lines[0]!.analogs).toEqual([]);
    expect(order.request).toEqual(request);
    expect(order.lines[0]!.part.geometry).toEqual(request.parts[0]!.geometry);
    expect(order.lines[0]!.uncertainties.join(" ")).toContain("tolerance: unknown");
    expect(order.provenance.register_sha256).toBeNull();
    expect(order.provenance.request_sha256).toBe(createHash("sha256").update(JSON.stringify(request)).digest("hex"));
    const result = spawnSync(process.execPath, [join(root, "estimator/node_modules/tsx/dist/cli.mjs"), join(root, "estimator/src/order-cli.ts"), join(directory, "request.json"), "--out", join(home, "order")], { env: { HOME: home, PATH: process.env.PATH }, encoding: "utf8" });
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(readFileSync(join(home, "order/order.json"), "utf8")).total).toBe(120);
  });

  it("holds should-cost completion for a conflict outside the worksheet links", async () => {
    const { request } = capture();
    request.parts[0]!.geometry!.find(f => f.id === "length")!.applicability = "conflict";
    const order = await buildPricedOrder(new QuoteRegister([]), request, { registerSha256: null });
    expect(order.lines[0]!.unit_price).toBe(120);
    expect(order.state).toBe("BLOCKED");
    expect(order.total).toBeNull();
    expect(order.blockers.join(" ")).toContain("explicit engineering conflict: finished_length");
  });

  it.each(groups)("rejects unretained cost locators in %s even with valid-looking hashes", group => {
    const request = externalRequest();
    const source = worksheet(request)[group][0]!.sources[0]!;
    for (const locator of ["upload:worksheet", "keller-intake:00000000-0000-0000-0000-000000000000/attachment-0.bin"]) {
      source.locator = locator;
      expect(() => assertOrderRequest(request)).toThrow(/unresolved upload|does not bind retained attachment/);
    }
  });

  it.each(groups)("checks every retained source in %s, not only the engineering-linked one", group => {
    const { request } = capture();
    const sources = worksheet(request)[group][0]!.sources;
    const source = structuredClone(sources[0]!);
    sources.push(source);
    source.sha256 = "0".repeat(64);
    expect(() => assertOrderRequest(request)).toThrow(/does not bind retained attachment/);
    source.sha256 = sources[0]!.sha256;
    source.locator = source.locator.replace("attachment-1.bin", "attachment-19.bin");
    expect(() => assertOrderRequest(request)).toThrow(/does not bind retained attachment/);
    source.locator = request.intake!.original_request.locator;
    source.sha256 = request.intake!.original_request.sha256;
    expect(() => assertOrderRequest(request)).toThrow(/does not bind retained attachment/);
  });

  it("rejects a forged retained cost reference already present before capture", () => {
    const request = JSON.parse(readFileSync(fixture, "utf8")) as OrderRequest;
    const sources = worksheet(request).not_applicable[0]!.sources;
    sources.push({ ...sources[0]!, sha256: "0".repeat(64),
      locator: "keller-intake:00000000-0000-0000-0000-000000000000/attachment-0.bin" });
    const path = join(home, "forged.json"); writeFileSync(path, JSON.stringify(request));
    expect(() => capture(path)).toThrow(/does not bind retained attachment/);
  });

  it("rejects unresolved engineering uploads without pretending the placeholder is evidence", () => {
    const request = externalRequest();
    request.parts[0]!.source_evidence = [{ id: "pending", sha256: "0".repeat(64), locator: "upload:drawing" }];
    expect(() => assertOrderRequest(request)).toThrow(/unresolved upload/);
  });

  it("preserves external approved estimates without claiming retained-byte verification", async () => {
    const request = externalRequest();
    expect(() => assertOrderRequest(request)).not.toThrow();
    const order = await buildPricedOrder(new QuoteRegister([]), request, { registerSha256: null });
    expect(order.total).toBe(120);
    expect(order.lines[0]!.cost_breakdown!.assertion_status).toBe("supplied_not_authenticated");
    expect(order.lines[0]!.cost_breakdown!.supplied_basis).toEqual(worksheet(request));
    expect(order.requires_human_review).toBe(true);
    const path = join(home, "external.json"); writeFileSync(path, JSON.stringify(request));
    const retained = capture(path);
    expect(() => verifyRetainedIntake(retained.request)).not.toThrow();
    expect(worksheet(retained.request)).toEqual(worksheet(request));
  });

  it("rejects changed original input, forged hashes, unknown worksheet facts and symlink escapes", () => {
    const { request, directory } = capture();
    const altered = structuredClone(request); altered.parts[0]!.quantity = 2;
    expect(() => verifyRetainedIntake(altered)).toThrow(/differs from retained original/);
    const forged = structuredClone(request); forged.intake!.attachments[0]!.sha256 = "0".repeat(64);
    expect(() => verifyRetainedIntake(forged)).toThrow();
    const unknown = structuredClone(request); unknown.parts[0]!.geometry!.find(f => f.id === "route")!.applicability = "unknown";
    expect(() => assertOrderRequest(unknown)).toThrow(/usable reviewed engineering facts/);
    const badUom = structuredClone(request); badUom.parts[0]!.uom!.pieces_per_original_unit = 12;
    expect(() => assertOrderRequest(badUom)).toThrow(/reconcile/);
    const file = join(directory, "attachment-0.bin"); chmodSync(directory, 0o700); rmSync(file); symlinkSync(join(home, "drawing.txt"), file); chmodSync(directory, 0o500);
    expect(() => verifyRetainedIntake(request)).toThrow();
  });

  it("detects changed retained bytes, requires a new capture and never silently uses history", async () => {
    const { request, directory } = capture();
    const file = join(directory, "attachment-0.bin"); chmodSync(file, 0o600); writeFileSync(file, "changed"); chmodSync(file, 0o400);
    expect(() => verifyRetainedIntake(request)).toThrow(/hash mismatch/);
    const mixed = { ...request, parts: [...request.parts, { line_id: "2", part_no: "OTHER", quantity: 1 }] };
    expect(requiresHistoricalRegister(mixed)).toBe(true);
    await expect(buildPricedOrder(new QuoteRegister([]), mixed, { registerSha256: null })).rejects.toThrow(/explicit register/);
    const plain = join(home, "mixed.json"); writeFileSync(plain, JSON.stringify({ ...mixed, intake: undefined, parts: [{ line_id: "2", part_no: "OTHER", quantity: 1 }] }));
    const result = spawnSync(process.execPath, [join(root, "estimator/node_modules/tsx/dist/cli.mjs"), join(root, "estimator/src/order-cli.ts"), plain, "--out", join(home, "blocked")], { encoding: "utf8" });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain("explicit --register");
    expect(existsSync(join(home, "blocked"))).toBe(false);
  });
});
