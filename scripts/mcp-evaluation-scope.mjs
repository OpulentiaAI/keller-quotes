import { createHash } from 'node:crypto'
import { closeSync, constants, fstatSync, lstatSync, openSync, readFileSync, realpathSync } from 'node:fs'
import { dirname, isAbsolute, join, parse, relative, resolve, sep } from 'node:path'

const hex = /^[a-f0-9]{64}$/
const names = new Set(['read_file_pinned', 'au_diagnostics', 'au_type', 'keller_quote', 'keller_polygres'])
const priceFields = ['quote_no', 'item_no', 'quantity', 'unit_price', 'extended_price', 'quote_date', 'letter_date', 'date_stamp', 'part_no', 'customer_id', 'source_price_field', 'price_basis', 'status', 'source_path', 'pdf_sha256', 'transcript_sha256']
const rowFields = ['quote_no', 'item_no', 'quantity', 'unit_price', 'extended_price', 'quote_date', 'letter_date', 'part_no', 'customer_id', 'source_price_field', 'price_basis', 'status']
const basis = 'verified issued customer quotation PDF'
const textBasis = 'PDF page text; not verified numeric price'
const publicContracts = new Set(['docs/pricing-evals-and-orders.md', 'estimator/src/order.ts', 'estimator/src/types.ts'])

export class ScopedPaginationError extends Error {
  constructor(message) {
    super(message)
    this.code = 'INVALID_PAGINATION_ARGUMENTS'
  }
}

function object(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key))) throw new Error('Invalid evaluation scope or guarded response')
  return value
}

function fields(value, keys) {
  object(value, keys)
  if (keys.some(key => !Object.hasOwn(value, key))) throw new Error('Invalid evaluation scope or guarded response')
  return value
}

function date(value, optional = false) {
  if (optional && value === '') return true
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
}

function decimal(value) {
  if (typeof value !== 'string' && (typeof value !== 'number' || !Number.isFinite(value))) throw new Error('Invalid decimal')
  const match = /^([+-]?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(String(value))
  if (!match || String(value).length > 128) throw new Error('Invalid decimal')
  const exponent = Number(match[4] ?? 0) - (match[3]?.length ?? 0)
  if (Math.abs(exponent) > 128) throw new Error('Invalid decimal')
  let digits = BigInt(match[2] + (match[3] ?? '')) * (match[1] === '-' ? -1n : 1n)
  if (exponent >= 0) digits *= 10n ** BigInt(exponent)
  return [digits, Math.max(0, -exponent)]
}

export function sameDecimal(a, b) {
  try {
    const [left, lp] = decimal(a), [right, rp] = decimal(b)
    return left * 10n ** BigInt(rp) === right * 10n ** BigInt(lp)
  } catch { return false }
}

export function priceKey(row) {
  let [quantity, scale] = decimal(row.quantity)
  while (scale && quantity % 10n === 0n) {
    quantity /= 10n
    scale--
  }
  return JSON.stringify([row.quote_no, row.item_no, row.source_path, `${quantity}:${scale}`])
}

function safePath(path) {
  if (typeof path !== 'string' || !isAbsolute(path) || resolve(path) !== path || path.split(sep).includes('..')) throw new Error('Unsafe evaluation scope path')
  let current = parse(path).root
  for (const part of path.slice(current.length).split(sep).filter(Boolean)) {
    current = join(current, part)
    const stat = lstatSync(current)
    if (stat.isSymbolicLink() || ![process.getuid(), 0].includes(stat.uid)) throw new Error('Unsafe evaluation scope path')
    if (current !== path && (!stat.isDirectory() || ((stat.mode & 0o022) && !(stat.uid === 0 && (stat.mode & 0o1000))))) throw new Error('Unsafe evaluation scope path')
  }
  const parent = lstatSync(dirname(path))
  if (parent.uid !== process.getuid() || (parent.mode & 0o077)) throw new Error('Evaluation scope directory must be private')
}

export function loadEvaluationScope(path, publicRoot = process.cwd()) {
  safePath(path)
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW)
  let bytes, stat
  try {
    stat = fstatSync(fd)
    if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || (stat.mode & 0o177) || stat.size > 128 * 1024 * 1024) throw new Error('Evaluation scope must be a private regular file')
    bytes = readFileSync(fd)
    if (bytes.length !== stat.size) throw new Error('Evaluation scope changed while reading')
  } finally { closeSync(fd) }
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  let scope
  try { scope = JSON.parse(bytes.toString('utf8')) } catch { throw new Error('Invalid evaluation scope JSON') }
  fields(scope, ['schema_version', 'case_id', 'corpus', 'quote_date', 'excluded_quote_nos', 'request', 'eligible_prices', 'allowed_files'])
  if (scope.schema_version !== 1 || typeof scope.case_id !== 'string' || !scope.case_id.trim() || !hex.test(scope.corpus) || !date(scope.quote_date) ||
      !Array.isArray(scope.excluded_quote_nos) || !scope.excluded_quote_nos.length || scope.excluded_quote_nos.some(x => typeof x !== 'string' || !x.trim()) ||
      new Set(scope.excluded_quote_nos).size !== scope.excluded_quote_nos.length || !Array.isArray(scope.eligible_prices) || !Array.isArray(scope.allowed_files)) throw new Error('Invalid evaluation scope')
  fields(scope.request, ['order_id', 'quote_date', 'customer', 'customer_id', 'reviewer', 'parts', 'charges'])
  for (const key of ['order_id', 'customer', 'customer_id', 'reviewer']) if (typeof scope.request[key] !== 'string' || !scope.request[key].trim()) throw new Error('Invalid evaluation request')
  if (scope.request.quote_date !== scope.quote_date || !Array.isArray(scope.request.parts) || !scope.request.parts.length || scope.request.parts.length > 50) throw new Error('Invalid evaluation request')
  const lines = new Set()
  for (const part of scope.request.parts) {
    fields(part, ['line_id', 'part_no', 'quantity'])
    if (typeof part.line_id !== 'string' || !part.line_id.trim() || lines.has(part.line_id) || typeof part.part_no !== 'string' || !part.part_no.trim() || !Number.isSafeInteger(part.quantity) || part.quantity <= 0) throw new Error('Invalid evaluation line')
    lines.add(part.line_id)
  }
  fields(scope.request.charges, ['shipping', 'tax'])
  for (const value of Object.values(scope.request.charges)) if (!sameDecimal(value, value) || decimal(value)[0] < 0n) throw new Error('Invalid evaluation charges')
  const identities = new Set(), documents = new Map(), prices = new Map(), analogs = new Map()
  for (const row of scope.eligible_prices) {
    fields(row, priceFields)
    if (['quote_no', 'part_no', 'customer_id', 'source_path'].some(key => typeof row[key] !== 'string' || !row[key].trim()) ||
        typeof row.item_no !== 'string' ||
        row.source_path.split('/').includes('..') || row.source_path.startsWith('/') ||
        !['PRICE', 'QUOTEPRICE'].includes(row.source_price_field) || row.price_basis !== 'customer_quote_pdf' || row.status !== 'unknown' ||
        !hex.test(row.pdf_sha256) || !hex.test(row.transcript_sha256) || scope.excluded_quote_nos.includes(row.quote_no) ||
        !date(row.quote_date) || !date(row.letter_date) || !date(row.date_stamp, true) ||
        row.quote_date >= scope.quote_date || row.letter_date >= scope.quote_date || (row.date_stamp && row.date_stamp >= scope.quote_date) ||
        !sameDecimal(row.quantity, row.quantity) || decimal(row.quantity)[0] <= 0n ||
        !sameDecimal(row.unit_price, row.unit_price) || decimal(row.unit_price)[0] <= 0n ||
        !sameDecimal(row.extended_price, row.extended_price) || decimal(row.extended_price)[0] <= 0n) throw new Error('Invalid eligible price')
    const identity = priceKey(row)
    if (identities.has(identity) || (documents.has(row.source_path) && documents.get(row.source_path) !== row.pdf_sha256)) throw new Error('Conflicting eligible evidence')
    identities.add(identity)
    documents.set(row.source_path, row.pdf_sha256)
    prices.set(identity, row)
    const group = analogs.get(row.quote_no) ?? []
    group.push(row)
    analogs.set(row.quote_no, group)
  }
  const allowed = new Set()
  for (const file of scope.allowed_files) {
    if (typeof file !== 'string' || !isAbsolute(file) || file.split(sep).includes('..') || realpathSync(file) !== file || !lstatSync(file).isFile()) throw new Error('Invalid allowed file')
    const within = relative(publicRoot, file)
    if (within.startsWith('..' + sep) || within === '..' ||
        (!publicContracts.has(within.replaceAll(sep, '/')) &&
         !/^(?:\.agents\/skills\/[^/]+\/SKILL\.md|type\/[^/]+\.type\.yaml|docs\/[^/]*synthetic[^/]*|scripts\/test\/[^/]*synthetic[^/]*)$/.test(within.replaceAll(sep, '/')))) throw new Error('Invalid allowed public file')
    allowed.add(file)
  }
  const verify = () => {
    safePath(path)
    const current = lstatSync(path)
    if (current.dev !== stat.dev || current.ino !== stat.ino || current.size !== stat.size || createHash('sha256').update(readFileSync(path)).digest('hex') !== sha256) throw new Error('Evaluation scope changed')
  }
  verify()
  return { scope, path, sha256, fileIdentity: { dev: stat.dev, ino: stat.ino }, verify, documents, allowed, prices, analogs }
}

function matchesPrice(price, row) {
  if (!price || !row || price.source_path !== row.source_path || price.pdf_sha256 !== row.pdf_sha256 || price.transcript_sha256 !== row.transcript_sha256) return false
  return rowFields.every(key => ['quantity', 'unit_price', 'extended_price'].includes(key)
    ? sameDecimal(price.row[key], row[key]) : price.row[key] === row[key])
}

function requestMatches(value, scope) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      ['order_id', 'quote_date', 'customer', 'customer_id'].some(key => value[key] !== scope.request[key]) ||
      !Array.isArray(value.parts) || value.parts.length !== scope.request.parts.length ||
      !value.parts.every((part, i) => part?.line_id === scope.request.parts[i].line_id && part.part_no === scope.request.parts[i].part_no && part.quantity === scope.request.parts[i].quantity) ||
      !value.charges || Object.keys(value.charges).some(key => !['shipping', 'tax'].includes(key)) ||
      !['shipping', 'tax'].every(key => sameDecimal(value.charges[key], scope.request.charges[key])) ||
      (value.additional_charges !== undefined && (!Array.isArray(value.additional_charges) || value.additional_charges.length))) throw new Error('Evaluation quote request mismatch')
}

export function beforeScopedCall(name, input, guard) {
  guard.verify()
  const { scope, documents, allowed } = guard
  if (!names.has(name)) throw new Error('Tool unavailable in evaluation scope')
  if (name === 'read_file_pinned') {
    const path = object(input, ['file_path', 'offset', 'limit']).file_path
    if (!allowed.has(path) || realpathSync(path) !== path || !lstatSync(path).isFile()) throw new Error('File unavailable in evaluation scope')
    for (const key of ['offset', 'limit']) if (input[key] !== undefined && (!Number.isSafeInteger(input[key]) || input[key] < 1)) throw new Error('Invalid pinned read bounds')
  }
  if (name === 'au_diagnostics' && Object.entries(object(input, ['limit'])).some(([key, value]) => key !== 'limit' || !Number.isSafeInteger(value) || value < 1 || value > 10)) throw new Error('Diagnostics unavailable in evaluation scope')
  if (name === 'au_type') {
    object(input, ['name'])
    if (typeof input.name !== 'string' || !/^(?:mcp\.tool(?:\.|::)|mcp\.skill::)/.test(input.name)) throw new Error('Type unavailable in evaluation scope')
    if (/^mcp\.tool(?:\.|::)keller_quote(?:[.:]|$)/.test(input.name)) throw new Error('Use scoped tool discovery for quote inputs')
  }
  if (name === 'keller_polygres') {
    const action = input?.action
    const keys = { corpora: ['action'], prices: ['action', 'corpus', 'part_no', 'quote_no', 'limit', 'offset'], search: ['action', 'corpus', 'query', 'quote_no', 'kind', 'limit', 'offset'], page: ['action', 'corpus', 'source_path', 'page_number', 'limit', 'offset'] }[action]
    if (!keys) throw new Error('Evidence action unavailable')
    object(input, keys)
    if (action !== 'corpora' && input.corpus !== scope.corpus) throw new Error('Evaluation corpus mismatch')
    if (input.quote_no !== undefined && scope.excluded_quote_nos.includes(input.quote_no)) throw new Error('Excluded quote selector')
    if (action === 'page' && !documents.has(input.source_path)) throw new Error('Page unavailable in evaluation scope')
    if (action !== 'corpora') {
      const page = action === 'page'
      const maxLimit = page ? 4000 : 50
      const maxOffset = page ? 1000000 : 100000
      if (input.limit !== undefined && (!Number.isSafeInteger(input.limit) || input.limit < 1 || input.limit > maxLimit)) {
        throw new ScopedPaginationError(page ? 'page limit must be an integer from 1 to 4000' : 'prices/search limit must be an integer from 1 to 50')
      }
      if (input.offset !== undefined && (!Number.isSafeInteger(input.offset) || input.offset < 0 || input.offset > maxOffset)) {
        throw new ScopedPaginationError(page ? 'page offset must be an integer from 0 to 1000000' : 'prices/search offset must be an integer from 0 to 100000')
      }
      if (page && (!Number.isSafeInteger(input.page_number) || input.page_number < 1 || input.page_number > 100000)) {
        throw new ScopedPaginationError('page_number must be an integer from 1 to 100000')
      }
    }
  }
  if (name === 'keller_quote') {
    fields(input, ['corpus', 'request', 'reviewer'])
    if (input.corpus !== scope.corpus || input.reviewer !== scope.request.reviewer || typeof input.request !== 'string') throw new Error('Evaluation quote identity mismatch')
    let parsed
    try { parsed = JSON.parse(input.request) } catch { throw new Error('Invalid evaluation quote request') }
    requestMatches(parsed, scope)
  }
}

export function afterScopedCall(name, input, result, guard) {
  guard.verify()
  if (name === 'read_file_pinned') {
    const path = input.file_path
    if (!guard.allowed.has(path) || realpathSync(path) !== path || !lstatSync(path).isFile()) throw new Error('Pinned file changed')
  }
  if (!result || Object.keys(object(result, ['content', 'isError'])).some(key => key === 'isError' && result[key] !== false) ||
      !Array.isArray(result.content) || result.content.length !== 1 ||
      Object.keys(object(result.content[0], ['type', 'text'])).length !== 2 || result.content[0].type !== 'text' || typeof result.content[0].text !== 'string') throw new Error('Guarded MCP response unavailable')
  if (!['keller_quote', 'keller_polygres'].includes(name)) return result
  let payload
  try { payload = JSON.parse(result.content[0].text) } catch { throw new Error('Invalid guarded MCP payload') }
  object(payload, Object.keys(payload))
  const { scope, documents } = guard
  if (name === 'keller_quote') {
    object(payload, ['draft_id', 'state', 'review_status', 'reviewer', 'requires_human_review', 'total', 'blockers', 'order', 'markdown', 'review', 'price_bases', 'warning', 'corpus_id', 'corpus_sha256', 'source_rows', 'request_sha256', 'artifacts', 'evaluation_scope_sha256'])
    object(payload.order, ['schema_version', 'request', 'order_id', 'quote_date', 'customer', 'currency', 'state', 'requires_human_review', 'lines', 'charges', 'additional_charges', 'priced_subtotal', 'subtotal', 'total', 'blockers', 'warnings', 'provenance'])
    object(payload.review, ['status', 'reviewer', 'requires_human_review', 'customer_release_authorized', 'state', 'corpus_id', 'corpus_sha256', 'request_sha256', 'warning', 'evaluation_scope_sha256', 'source_rows'])
    if (payload.evaluation_scope_sha256 !== guard.sha256 ||
        payload.review.evaluation_scope_sha256 !== guard.sha256 ||
        payload.source_rows !== scope.eligible_prices.length ||
        payload.review.source_rows !== scope.eligible_prices.length) throw new Error('Scoped register proof mismatch')
    const submittedSha = createHash('sha256').update(JSON.stringify(JSON.parse(input.request))).digest('hex')
    if (payload.reviewer !== scope.request.reviewer || payload.corpus_id !== scope.corpus ||
        payload.review?.reviewer !== scope.request.reviewer || payload.review?.corpus_id !== scope.corpus ||
        payload.review?.state !== payload.state ||
        payload.review?.status !== 'PENDING_NAMED_HUMAN_REVIEW' || payload.review?.requires_human_review !== true ||
        payload.review?.customer_release_authorized !== false || payload.requires_human_review !== true ||
        payload.order?.requires_human_review !== true ||
        (payload.quote_date !== undefined && payload.quote_date !== scope.quote_date) ||
        (payload.review.quote_date !== undefined && payload.review.quote_date !== scope.quote_date) ||
        payload.request_sha256 !== submittedSha || payload.review.request_sha256 !== submittedSha ||
        payload.order?.provenance?.request_sha256 !== submittedSha ||
        payload.review.corpus_sha256 !== payload.corpus_sha256 || payload.order?.provenance?.register_sha256 !== payload.corpus_sha256 ||
        payload.order?.quote_date !== scope.quote_date || payload.order?.order_id !== scope.request.order_id ||
        payload.order?.customer !== scope.request.customer || payload.order?.provenance?.as_of !== scope.quote_date ||
        !Array.isArray(payload.order?.lines) || payload.order.lines.length !== scope.request.parts.length ||
        !['BLOCKED', 'PRICED_REQUIRES_REVIEW'].includes(payload.state) || payload.order.state !== payload.state ||
        !['BLOCKED', 'PRICED_REQUIRES_REVIEW'].includes(payload.review?.state)) throw new Error('Guarded quote mismatch')
    requestMatches(payload.order.request, scope)
    for (const [i, line] of payload.order.lines.entries()) {
      object(line, ['line_id', 'part', 'unit_price', 'extended_price', 'pricing_source', 'pricing_reason', 'confidence', 'analogs', 'warnings'])
      if (line?.line_id !== scope.request.parts[i].line_id || line.part?.part_no !== scope.request.parts[i].part_no ||
          line.part?.quantity !== scope.request.parts[i].quantity || !Array.isArray(line.analogs)) throw new Error('Guarded quote line mismatch')
      for (const analog of line.analogs) {
        object(analog, ['quote_no', 'quote_date', 'date_stamp', 'rev', 'customer', 'part_no', 'description', 'status', 'score', 'jev_probability', 'price_evidence', 'quote_letter', 'letter_date'])
        object(analog.price_evidence, ['price_basis', 'source_document', 'source_document_sha256', 'source_transcript_sha256', 'source_price_field'])
        if (!(guard.analogs.get(analog.quote_no) ?? []).some(row => row.quote_no === analog.quote_no && row.quote_date === analog.quote_date &&
            row.letter_date === analog.letter_date && row.date_stamp === (analog.date_stamp ?? '') && row.part_no === analog.part_no &&
            row.status === analog.status && analog.price_evidence?.price_basis === 'customer_quote_pdf' &&
            analog.price_evidence.source_document === row.source_path && analog.price_evidence.source_document_sha256 === row.pdf_sha256 &&
            analog.price_evidence.source_transcript_sha256 === row.transcript_sha256 && analog.price_evidence.source_price_field === row.source_price_field)) throw new Error('Ineligible quote analog')
      }
    }
    if (!['shipping', 'tax'].every(key => sameDecimal(payload.order.charges?.[key], scope.request.charges[key])) ||
        !Array.isArray(payload.order.additional_charges) || payload.order.additional_charges.length) throw new Error('Guarded quote charges mismatch')
    return result
  }
  const action = input.action
  if (payload.action !== action || (action !== 'corpora' && payload.corpus !== scope.corpus)) throw new Error('Guarded evidence mismatch')
  if (action === 'corpora') {
    fields(payload, ['action', 'corpora', 'has_more'])
    if (!Array.isArray(payload.corpora) || typeof payload.has_more !== 'boolean') throw new Error('Invalid corpora')
    payload.corpora = payload.corpora.filter(item => {
      fields(item, ['corpus', 'documents', 'pages', 'verified_prices'])
      if (!hex.test(item.corpus) || [item.documents, item.pages, item.verified_prices].some(value => !Number.isSafeInteger(value) || value < 0)) throw new Error('Invalid corpus metadata')
      return item.corpus === scope.corpus
    })
    payload.has_more = false
  } else if (action === 'prices') {
    fields(payload, ['action', 'corpus', 'basis', 'outcome', 'prices', 'has_more', 'next_offset'])
    if (payload.basis !== basis || payload.outcome !== 'unknown' || !Array.isArray(payload.prices)) throw new Error('Invalid prices')
    payload.prices = payload.prices.filter(price => {
      fields(price, ['row', 'source_path', 'pdf_sha256', 'transcript_sha256'])
      fields(price.row, rowFields)
      if (typeof price.source_path !== 'string' || !hex.test(price.pdf_sha256) || !hex.test(price.transcript_sha256)) throw new Error('Invalid price provenance')
      const row = guard.prices.get(priceKey({ ...price.row, source_path: price.source_path }))
      return row !== undefined && matchesPrice(price, row)
    })
  } else if (action === 'search') {
    fields(payload, ['action', 'corpus', 'basis', 'hits', 'has_more', 'next_offset'])
    if (payload.basis !== textBasis || !Array.isArray(payload.hits)) throw new Error('Invalid search')
    payload.hits = payload.hits.filter(hit => {
      fields(hit, ['source_path', 'page_number', 'page_sha256', 'pdf_sha256', 'kind', 'excerpt'])
      if (typeof hit.source_path !== 'string' || !Number.isSafeInteger(hit.page_number) || hit.page_number < 1 ||
          !hex.test(hit.pdf_sha256) || !hex.test(hit.page_sha256) || typeof hit.excerpt !== 'string' ||
          !['quote', 'invoice', 'packing_slip', 'supplier_po', 'certificate', 'other', 'unknown'].includes(hit.kind)) throw new Error('Invalid search hit')
      return hit.kind === 'quote' && documents.get(hit.source_path) === hit.pdf_sha256
    })
  } else {
    fields(payload, ['action', 'corpus', 'source_path', 'page_number', 'page_count', 'pdf_sha256', 'page_sha256', 'kind', 'basis', 'text', 'has_more', 'next_offset'])
    if (payload.source_path !== input.source_path || payload.page_number !== input.page_number || payload.kind !== 'quote' ||
        payload.pdf_sha256 !== documents.get(input.source_path) || payload.basis !== textBasis ||
        !Number.isSafeInteger(payload.page_count) || payload.page_number < 1 || payload.page_number > payload.page_count ||
        typeof payload.text !== 'string' || !hex.test(payload.page_sha256)) throw new Error('Ineligible source page')
  }
  if (action === 'prices' || action === 'search' || action === 'page') {
    if (typeof payload.has_more !== 'boolean' || (payload.has_more && (!Number.isSafeInteger(payload.next_offset) || payload.next_offset <= (input.offset ?? 0))) ||
        (!payload.has_more && payload.next_offset !== null)) throw new Error('Invalid evidence pagination')
  }
  return { content: [{ type: 'text', text: JSON.stringify(payload) }], ...(result.isError === false ? { isError: false } : {}) }
}

export function scopedToolList(result, guard) {
  guard.verify()
  if (!result || !Array.isArray(result.tools) || result.tools.some(tool => !tool || typeof tool.name !== 'string')) throw new Error('Invalid guarded tools list')
  return { tools: result.tools.filter(tool => names.has(tool.name)).map(tool => {
    if (tool.name === 'keller_quote') {
      return { ...tool, inputSchema: tool.inputSchema ? { ...tool.inputSchema,
        properties: Object.fromEntries(Object.entries(tool.inputSchema.properties ?? {}).filter(([key]) => !['evaluation_scope_path', 'evaluation_scope_sha256'].includes(key))),
        required: tool.inputSchema.required?.filter(key => !['evaluation_scope_path', 'evaluation_scope_sha256'].includes(key)),
      } : tool.inputSchema }
    }
    if (tool.name !== 'keller_polygres') return tool
    object(tool.inputSchema, Object.keys(tool.inputSchema))
    if (tool.inputSchema.type !== 'object' || !tool.inputSchema.properties?.limit) throw new Error('Invalid evidence discovery schema')
    return { ...tool,
      description: `${tool.description ?? ''} Scoped pagination: prices/search limit 1..50 rows (default 20), offset 0..100000; page limit 1..4000 characters (default 4000), offset 0..1000000, page_number 1..100000. Follow next_offset even after an empty filtered page.`,
      inputSchema: { ...tool.inputSchema,
        properties: { ...tool.inputSchema.properties,
          limit: { ...tool.inputSchema.properties.limit, description: 'prices/search: 1..50 rows (default 20); page: 1..4000 characters (default 4000).' },
          offset: { ...tool.inputSchema.properties.offset, description: 'prices/search: 0..100000; page: 0..1000000.' } },
        allOf: [
          { if: { properties: { action: { enum: ['prices', 'search'] } }, required: ['action'] }, then: { properties: { limit: { maximum: 50 }, offset: { maximum: 100000 } } } },
          { if: { properties: { action: { const: 'page' } }, required: ['action'] }, then: { properties: { limit: { maximum: 4000 }, offset: { maximum: 1000000 }, page_number: { maximum: 100000 } } } },
        ] },
    }
  }) }
}
