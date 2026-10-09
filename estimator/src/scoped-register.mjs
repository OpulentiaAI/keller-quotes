import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { parse } from 'csv-parse/sync'
import { beforeScopedCall, loadEvaluationScope, priceKey, sameDecimal } from '../../scripts/mcp-evaluation-scope.mjs'

const fields = {
  source_path: 'source_document', pdf_sha256: 'source_document_sha256',
  transcript_sha256: 'source_transcript_sha256',
}
const numeric = new Set(['quantity', 'unit_price', 'extended_price'])

export function scopedRegister(scopePath, scopeSha, publicRoot, corpus, request, reviewer, source, sourceSha, destination) {
  const guard = loadEvaluationScope(scopePath, publicRoot)
  if (guard.sha256 !== scopeSha || guard.scope.corpus !== corpus || guard.scope.request.reviewer !== reviewer) {
    throw new Error('Evaluation scope binding mismatch')
  }
  const original = { corpus, request: JSON.stringify(request), reviewer }
  beforeScopedCall('keller_quote', original, guard)
  const verify = () => beforeScopedCall('keller_quote', original, guard)

  const sourceBytes = readFileSync(source)
  if (createHash('sha256').update(sourceBytes).digest('hex') !== sourceSha) throw new Error('Verified export changed')
  const records = parse(sourceBytes, { bom: true, skip_empty_lines: true })
  const [header, ...data] = records
  const required = new Set(Object.keys(guard.scope.eligible_prices[0] ?? {}).map(key => fields[key] ?? key))
  if (!header || new Set(header).size !== header.length || [...required].some(key => !header.includes(key)) ||
      data.some(row => row.length !== header.length)) throw new Error('Invalid verified register columns')
  const rows = new Map()
  for (const values of data) {
    const row = Object.fromEntries(header.map((field, index) => [field, values[index]]))
    const key = priceKey({ ...row, source_path: row.source_document })
    if (rows.has(key)) throw new Error('Duplicate verified price break')
    rows.set(key, { row, values })
  }
  const selected = new Set()
  for (const eligible of guard.scope.eligible_prices) {
    const found = rows.get(priceKey(eligible))
    if (!found || Object.keys(eligible).some(key => {
      const actual = found.row[fields[key] ?? key]
      return numeric.has(key) ? !sameDecimal(actual, eligible[key]) : actual !== eligible[key]
    })) throw new Error('Eligible price missing or conflicts with verified register')
    selected.add(found)
  }
  verify()
  // Reconstruct only frozen fields. Use the frozen document locator as a scoped
  // source label, never a live/unfrozen customer quote-letter assertion.
  const columns = [...new Set([...Object.keys(guard.scope.eligible_prices[0] ?? fields).map(key => fields[key] ?? key), 'quote_letter'])]
  const csv = [columns, ...guard.scope.eligible_prices.map(eligible => {
    const row = Object.fromEntries(Object.entries(eligible).map(([key, value]) => [fields[key] ?? key, String(value)]))
    row.quote_letter = eligible.source_path
    return columns.map(key => row[key] ?? '')
  })]
    .map(values => values.map(value => /[",\r\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value).join(',')).join('\n') + '\n'
  writeFileSync(destination, csv, { flag: 'wx', mode: 0o600 })
  const sha256 = createHash('sha256').update(readFileSync(destination)).digest('hex')
  verify()
  return { sha256, rows: selected.size, verify }
}
