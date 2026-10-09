import { createHash, randomUUID } from "node:crypto";
import { chmodSync, closeSync, constants, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { CostBasis } from "./costing.js";

/** These are extraction/assertion records, not an automatic geometry verifier. */
export interface SourceEvidence {
  id: string; sha256: string; locator: string; attachment_id?: string;
  page?: number; record_index?: number; field?: string;
}
export interface EngineeringFact {
  id: string; field: string; value: string | null; original_unit?: string;
  source_ids: string[]; applicability: "supported" | "assumed" | "unknown" | "conflict";
  review?: { reviewer: string; reason: string };
}
export interface OriginalUom {
  original_unit: string; original_quantity: number; pieces_per_original_unit: number;
  conversion_basis: string; reviewer: string;
}
export interface RetainedSource { sha256: string; locator: string; size_bytes: number }
export interface Intake {
  schema_version: 1; operator: string; captured_at: string;
  original_request: RetainedSource;
  attachments: (RetainedSource & { id: string; media_type: string })[];
}
const hash = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const locatorPattern = /^keller-intake:([a-f0-9-]{36})\/(original-request\.json|attachment-[0-9]+\.bin)$/;
function record(v: unknown, keys: string[]): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v) || Object.keys(v).some(k => !keys.includes(k))) throw new Error("invalid engineering intake fields");
  return v as Record<string, unknown>;
}
function text(v: unknown): asserts v is string {
  if (typeof v !== "string" || !v.trim() || v.length > 2048 || /[\x00-\x08\x0b-\x1f\x7f]/.test(v)) throw new Error("engineering intake requires bounded nonblank text");
}
function list(v: unknown, max: number): unknown[] {
  if (!Array.isArray(v) || v.length > max) throw new Error("engineering intake array exceeds limits");
  return v;
}
function digest(v: unknown): void {
  if (typeof v !== "string" || !/^[a-f0-9]{64}$/.test(v)) throw new Error("engineering source requires lowercase SHA256");
}
function integer(v: unknown, minimum: number, maximum: number): void {
  if (!Number.isSafeInteger(v) || (v as number) < minimum || (v as number) > maximum) throw new Error("engineering source integer out of bounds");
}
function retained(v: unknown, attachment: boolean): void {
  const r = record(v, ["sha256", "locator", "size_bytes", ...(attachment ? ["id", "media_type"] : [])]);
  digest(r.sha256);
  if (typeof r.locator !== "string" || !locatorPattern.test(r.locator) || r.locator.endsWith("original-request.json") === attachment) throw new Error("invalid retained intake locator");
  integer(r.size_bytes, 1, attachment ? 32 * 1024 * 1024 : 128 * 1024);
  if (attachment) { text(r.id); text(r.media_type); }
}
export function assertIntake(value: unknown): asserts value is Intake {
  const i = record(value, ["schema_version", "operator", "captured_at", "original_request", "attachments"]);
  if (i.schema_version !== 1) throw new Error("unsupported intake schema");
  text(i.operator);
  if (typeof i.captured_at !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(i.captured_at) || new Date(i.captured_at).toISOString() !== i.captured_at) throw new Error("invalid intake capture date");
  retained(i.original_request, false);
  const ids = new Set();
  const locators = new Set();
  const prefix = (i.original_request as RetainedSource).locator.split("/")[0];
  let total = 0;
  for (const attachment of list(i.attachments, 20)) {
    retained(attachment, true);
    const a = attachment as Intake["attachments"][number];
    if (ids.has(a.id) || locators.has(a.locator) || !a.locator.startsWith(prefix + "/")) throw new Error("duplicate or foreign intake attachment");
    ids.add(a.id); locators.add(a.locator); total += a.size_bytes;
  }
  if (total > 64 * 1024 * 1024) throw new Error("intake attachment total exceeds 64 MiB");
}

function assertBoundSource(source: Pick<SourceEvidence, "sha256" | "locator">, intake?: Intake): void {
  if (source.locator.startsWith("upload:")) throw new Error("unresolved upload reference; retain intake before pricing");
  if (source.locator.startsWith("keller-intake:")) {
    const attachment = intake?.attachments.find(a => a.locator === source.locator);
    if (!attachment || attachment.sha256 !== source.sha256) throw new Error("source does not bind retained attachment");
  }
}

export function assertEngineeringLine(part: Record<string, unknown>, intake?: Intake): void {
  const evidence = new Map<string, SourceEvidence>();
  for (const value of list(part.source_evidence ?? [], 64)) {
    const s = record(value, ["id", "sha256", "locator", "attachment_id", "page", "record_index", "field"]);
    text(s.id); text(s.locator); digest(s.sha256);
    assertBoundSource(s as unknown as SourceEvidence, intake);
    if (evidence.has(s.id)) throw new Error("duplicate source_evidence id");
    if (s.page !== undefined) integer(s.page, 1, 100000);
    if (s.record_index !== undefined) integer(s.record_index, 0, 10000000);
    if (s.field !== undefined) text(s.field);
    if (s.attachment_id !== undefined) {
      text(s.attachment_id);
      const a = intake?.attachments.find(a => a.id === s.attachment_id);
      if (!a || a.sha256 !== s.sha256 || a.locator !== s.locator) throw new Error("source_evidence does not bind retained attachment");
    } else if (s.locator.startsWith("keller-intake:")) throw new Error("retained source requires attachment_id");
    evidence.set(s.id, s as unknown as SourceEvidence);
  }
  const facts = new Map<string, EngineeringFact>();
  for (const value of list(part.geometry ?? [], 64)) {
    const f = record(value, ["id", "field", "value", "original_unit", "source_ids", "applicability", "review"]);
    text(f.id); text(f.field);
    if (f.value !== null) text(f.value);
    if (f.original_unit !== undefined) text(f.original_unit);
    if (facts.has(f.id)) throw new Error("duplicate engineering fact id");
    if (!["supported", "assumed", "unknown", "conflict"].includes(f.applicability as string)) throw new Error("invalid engineering applicability");
    const refs = list(f.source_ids, 8);
    if (new Set(refs).size !== refs.length || refs.some(id => !evidence.has(id as string))) throw new Error("engineering fact source reference missing");
    if (["supported", "assumed"].includes(f.applicability as string) && (!refs.length || f.value === null || f.review === undefined)) throw new Error("usable engineering facts require source, value and named review");
    if (f.review !== undefined) {
      const review = record(f.review, ["reviewer", "reason"]); text(review.reviewer); text(review.reason);
    }
    facts.set(f.id, f as unknown as EngineeringFact);
  }
  if (part.uom !== undefined) {
    const u = record(part.uom, ["original_unit", "original_quantity", "pieces_per_original_unit", "conversion_basis", "reviewer"]);
    for (const key of ["original_unit", "conversion_basis", "reviewer"]) text(u[key]);
    for (const key of ["original_quantity", "pieces_per_original_unit"]) {
      if (typeof u[key] !== "number" || !Number.isFinite(u[key]) || (u[key] as number) <= 0 || (u[key] as number) > 1e9) throw new Error("invalid original UOM conversion");
    }
    if (Math.abs((u.original_quantity as number) * (u.pieces_per_original_unit as number) - (part.quantity as number)) > 1e-9) throw new Error("UOM conversion must reconcile to piece quantity");
  }
  // Optional explicit worksheet links make engineering-to-cost support inspectable.
  const pricing = part.pricing as { cost_basis?: CostBasis } | undefined;
  const basis = pricing?.cost_basis;
  for (const item of [...(basis?.components ?? []), ...(basis?.routing ?? []), ...(basis?.not_applicable ?? [])]) {
    for (const source of item.sources) assertBoundSource(source, intake);
  }
  for (const component of [...(basis?.components ?? []), ...(basis?.routing ?? [])]) {
    const c = component as { engineering_fact_ids?: string[]; sources?: { sha256: string; locator: string }[] };
    for (const id of list(c.engineering_fact_ids ?? [], 32)) {
      const fact = facts.get(id as string);
      if (!fact || !["supported", "assumed"].includes(fact.applicability) || !fact.review) throw new Error("worksheet requires usable reviewed engineering facts");
      if (!fact.source_ids.some(id => c.sources?.some(s => s.sha256 === evidence.get(id)!.sha256 && s.locator === evidence.get(id)!.locator))) throw new Error("worksheet engineering source does not match cost support");
    }
  }
}

export function intakeRoot(): string { return join(homedir(), ".local/share/keller-quotes/intake"); }
function privateStorage(create: boolean): void {
  for (const path of [join(homedir(), ".local"), join(homedir(), ".local/share"), join(homedir(), ".local/share/keller-quotes"), intakeRoot()]) {
    if (create && !existsSync(path)) mkdirSync(path, { mode: 0o700 });
    const stat = lstatSync(path);
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid?.() || realpathSync(path) !== path ||
        ([intakeRoot(), dirname(intakeRoot())].includes(path) && (stat.mode & 0o077))) throw new Error("private intake storage unavailable");
  }
}
function bytes(path: string, max: number, immutable = false): Buffer {
  if (realpathSync(dirname(path)) !== dirname(path)) throw new Error("source path must not traverse symlinks");
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = fstatSync(fd);
    if (!before.isFile() || before.size < 1 || before.size > max || (immutable && (before.uid !== process.getuid?.() || (before.mode & 0o377) || before.nlink !== 1))) throw new Error("invalid bounded intake source file");
    // Read at most the observed bounded size plus one sentinel byte, even if an upload grows.
    const buffer = Buffer.alloc(before.size + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = readSync(fd, buffer, length, buffer.length - length, null);
      if (!count) break;
      length += count;
    }
    const data = buffer.subarray(0, length);
    const after = fstatSync(fd);
    if (data.length !== before.size || before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) throw new Error("intake source changed during capture");
    return data;
  } finally { closeSync(fd); }
}
// The only intake transformation: resolve explicit upload IDs to captured hashes/locators.
// Applied again during verification against the retained original bytes.
function bindAttachments(original: Record<string, unknown>, attachments: Intake["attachments"]): Record<string, unknown> {
  const request = structuredClone(original);
  const bind = (source: Record<string, unknown>, id: unknown) => {
    const a = attachments.find(a => a.id === id);
    if (!a) throw new Error("unknown intake attachment reference");
    if (source.sha256 !== undefined && source.sha256 !== a.sha256) throw new Error("supplied attachment hash differs from captured bytes");
    if (source.locator !== undefined && source.locator !== `upload:${a.id}` && source.locator !== a.locator) throw new Error("supplied attachment locator conflicts with capture");
    source.sha256 = a.sha256; source.locator = a.locator;
  };
  for (const part of (request.parts ?? []) as Record<string, unknown>[]) {
    for (const source of (part.source_evidence ?? []) as Record<string, unknown>[]) {
      if (source.attachment_id !== undefined) bind(source, source.attachment_id);
    }
    const pricing = part.pricing as { cost_basis?: { components?: { sources?: Record<string, unknown>[] }[]; routing?: { sources?: Record<string, unknown>[] }[]; not_applicable?: { sources?: Record<string, unknown>[] }[] } } | undefined;
    const basis = pricing?.cost_basis;
    for (const item of [...(basis?.components ?? []), ...(basis?.routing ?? []), ...(basis?.not_applicable ?? [])]) {
      for (const source of item.sources ?? []) if (typeof source.locator === "string" && source.locator.startsWith("upload:")) bind(source, source.locator.slice(7));
    }
  }
  return request;
}

/** Verify retained bytes at quote time, not merely asserted locators/hashes. */
export function verifyRetainedIntake(request: { intake?: Intake }): void {
  if (!request.intake) return;
  assertIntake(request.intake);
  privateStorage(false);
  for (const source of [request.intake.original_request, ...request.intake.attachments]) {
    const match = locatorPattern.exec(source.locator)!;
    const dir = join(intakeRoot(), match[1]!);
    const stat = lstatSync(dir);
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid?.() || (stat.mode & 0o277)) throw new Error("retained intake directory is not private and immutable");
    const data = bytes(join(dir, match[2]!), source.size_bytes, true);
    if (data.length !== source.size_bytes || hash(data) !== source.sha256) throw new Error("retained intake source hash mismatch");
    if (source === request.intake.original_request) {
      const { intake: _intake, ...original } = request;
      if (JSON.stringify(bindAttachments(JSON.parse(data.toString("utf8")), request.intake.attachments)) !== JSON.stringify(original)) throw new Error("order differs from retained original input; retain a new intake for changed inputs");
    }
  }
}

/** Explicit local operator upload only. No mail ingestion, source execution or CAD inference. */
export function retainIntake(requestPath: string, uploads: unknown, operator: string,
  validate: (value: unknown) => void): { request: Record<string, unknown>; directory: string } {
  text(operator);
  const original = bytes(resolve(requestPath), 128 * 1024);
  const request = JSON.parse(original.toString("utf8")) as Record<string, unknown>;
  if (!request || typeof request !== "object" || Array.isArray(request) || request.intake !== undefined) throw new Error("retain expects an order without an existing intake");
  let remaining = 64 * 1024 * 1024;
  const inputs = list(uploads, 20).map(value => {
    const u = record(value, ["id", "path", "media_type"]); text(u.id); text(u.path); text(u.media_type);
    const data = bytes(resolve(u.path), Math.min(32 * 1024 * 1024, remaining));
    remaining -= data.length;
    return { id: u.id, media_type: u.media_type, data };
  });
  privateStorage(true);
  const id = randomUUID(), directory = join(intakeRoot(), id);
  mkdirSync(directory, { mode: 0o700 });
  try {
    const retain = (name: string, data: Buffer): RetainedSource => {
      writeFileSync(join(directory, name), data, { flag: "wx", mode: 0o400 });
      return { sha256: hash(data), locator: `keller-intake:${id}/${name}`, size_bytes: data.length };
    };
    const original_request = retain("original-request.json", original);
    const attachments = inputs.map((u, n) => ({ id: u.id, media_type: u.media_type, ...retain(`attachment-${n}.bin`, u.data) }));
    const intake: Intake = { schema_version: 1, operator, captured_at: new Date().toISOString(), original_request, attachments };
    const retained = { ...bindAttachments(request, attachments), intake };
    validate(retained);
    writeFileSync(join(directory, "request.json"), JSON.stringify(retained, null, 2) + "\n", { flag: "wx", mode: 0o400 });
    chmodSync(directory, 0o500);
    return { request: retained, directory };
  } catch (error) {
    chmodSync(directory, 0o700); rmSync(directory, { recursive: true, force: true }); throw error;
  }
}
