import { createHash } from "node:crypto";

export function selectCases<T extends { id: string }>(cases: T[], count: number, seed: string): T[] {
  if (!Number.isSafeInteger(count) || count < 0 || count > cases.length || !seed) {
    throw new Error("invalid sample count or seed");
  }
  return [...cases].sort((a, b) => {
    const hash = (id: string) => createHash("sha256").update(`${seed}\n${id}`).digest("hex");
    return hash(a.id).localeCompare(hash(b.id)) || a.id.localeCompare(b.id);
  }).slice(0, count);
}
