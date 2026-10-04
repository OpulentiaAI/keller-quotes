#!/usr/bin/env node
import { createHash, randomUUID } from 'node:crypto'
import { closeSync, constants, fstatSync, fsyncSync, linkSync, lstatSync, mkdirSync, openSync, readSync, readdirSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, parse, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const checkout = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const maxJson = 256 * 1024
const maxSource = 2 * 1024 * 1024
const maxEvents = 4096
const hex = /^[a-f0-9]{64}$/
const scopeKeys = ['workflow', 'customer_id', 'part_no', 'revision', 'material']
const sha = bytes => createHash('sha256').update(bytes).digest('hex')

function fail(code) {
  const error = new Error(code)
  error.code = code
  throw error
}

function shape(value, keys, required = keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value)) ||
      Reflect.ownKeys(value).some(key => !keys.includes(key)) ||
      required.some(key => !Object.hasOwn(value, key))) fail('INVALID_SCHEMA')
  return value
}

function encode(value, depth = 0, budget = { bytes: 0 }) {
  const add = fragment => {
    budget.bytes += Buffer.byteLength(fragment)
    if (budget.bytes > maxJson) fail('INPUT_TOO_LARGE')
    return fragment
  }
  if (depth > 12) fail('INPUT_TOO_LARGE')
  if (value === null || typeof value === 'boolean') return add(JSON.stringify(value))
  if (typeof value === 'number' && Number.isFinite(value)) return add(JSON.stringify(value))
  if (typeof value === 'string') {
    if (value.length > maxJson) fail('INPUT_TOO_LARGE')
    return add(JSON.stringify(value))
  }
  if (Array.isArray(value)) {
    if (value.length > 1000) fail('INPUT_TOO_LARGE')
    add(`[]${','.repeat(Math.max(0, value.length - 1))}`)
    return `[${Array.from(value, item => encode(item, depth + 1, budget)).join(',')}]`
  }
  if (value && typeof value === 'object' && [Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    const keys = Reflect.ownKeys(value)
    if (keys.length > 32 || keys.some(key => typeof key !== 'string')) fail('INVALID_SCHEMA')
    if (keys.some(key => key.length > maxJson)) fail('INPUT_TOO_LARGE')
    add(`{}${':'.repeat(keys.length)}${','.repeat(Math.max(0, keys.length - 1))}`)
    return `{${keys.sort().map(key => `${add(JSON.stringify(key))}:${encode(value[key], depth + 1, budget)}`).join(',')}}`
  }
  fail('INVALID_JSON')
}

function snapshot(value) {
  const bytes = Buffer.from(encode(value))
  if (bytes.length > maxJson) fail('INPUT_TOO_LARGE')
  return { value: JSON.parse(bytes.toString('utf8')), bytes, sha256: sha(bytes) }
}

function parseJson(bytes) {
  try {
    const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    const value = JSON.parse(source), objects = []
    for (let i = 0; i < source.length; i++) {
      if (source[i] === '"') {
        const start = i++
        while (source[i] !== '"') { if (source[i] === '\\') i++; i++ }
        let next = i + 1
        while (/[\t\n\r ]/.test(source[next] ?? '')) next++
        if (source[next] === ':') {
          const key = JSON.parse(source.slice(start, i + 1)), keys = objects.at(-1)
          if (!keys || keys.has(key)) fail('INVALID_JSON')
          keys.add(key)
        }
      } else if (source[i] === '{') objects.push(new Set())
      else if (source[i] === '[') objects.push(null)
      else if (source[i] === '}' || source[i] === ']') objects.pop()
    }
    return value
  } catch { fail('INVALID_JSON') }
}

function text(value, limit = 120) {
  if (typeof value !== 'string' || !value.trim() || value !== value.trim() || value.length > limit ||
      /[\u0000-\u001f\u007f]/u.test(value)) fail('INVALID_TEXT')
  return value
}

function safeMaterial(value) {
  if (/(?:-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|(?<![a-z0-9])(?:password|passwd|api[_ -]?key|client[_ -]?secret|secret|access[_ -]?token|auth[_ -]?token|token)(?![a-z0-9])\s*["']?\s*[:=]|\bauthorization\s*["']?\s*[:=]?\s*["']?\s*bearer\b|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b|\b[a-z][a-z0-9+.-]*:\/\/[^\s/:]+:[^\s/@]+@)/i.test(value)) fail('PROHIBITED_SECRET')
  if (/(?<![a-z0-9])(?:oracles?|hold[-_ ]?outs?|ground[-_ ]?truth|(?:hidden|target)[_ -]*(?:unit[_ -]*price|price|answer|unit|value|result|output)s?|(?:evaluation|eval|judge|criterion|case)[_ -]*(?:grade|score|result)s?|(?:agent|model)[_ -]*narrative)(?![a-z0-9])|["'](?:targets?|grades?|scores?|oracle|holdout)["']\s*:|\b(?:target|grade|score)\s*[:=]/i.test(value)) fail('PROHIBITED_EVALUATION_MATERIAL')
}

function date(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ||
      new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) fail('INVALID_DATE')
}

function identifier(value) {
  text(value)
  safeMaterial(value)
}

function hash(value) {
  if (typeof value !== 'string' || !hex.test(value)) fail('INVALID_HASH')
}

function inside(parent, path) {
  const rel = relative(parent, path)
  return rel === '' || (!rel.startsWith(`..${sep}`) && rel !== '..' && !isAbsolute(rel))
}

function pathSyntax(path) {
  if (typeof path !== 'string' || path.length > 1024 || !isAbsolute(path) || resolve(path) !== path ||
      path === parse(path).root || /[\u0000-\u001f\u007f]/u.test(path)) fail('UNSAFE_PATH')
  if (inside(checkout, path) || inside(path, checkout)) fail('CHECKOUT_PATH_DENIED')
}

function privatePath(path, directory = false) {
  pathSyntax(path)
  let current = parse(path).root
  for (const part of ['', ...path.slice(current.length).split(sep)]) {
    current = join(current, part)
    const stat = lstatSync(current)
    if (stat.isSymbolicLink() || ![process.getuid(), 0].includes(stat.uid)) fail('UNSAFE_PATH')
    if (current !== path && (!stat.isDirectory() || (stat.mode & 0o022))) fail('UNSAFE_PATH')
  }
  const parent = lstatSync(directory ? path : dirname(path))
  if (!parent.isDirectory() || parent.uid !== process.getuid() || (parent.mode & 0o7777) !== 0o700) fail('PRIVATE_DIRECTORY_REQUIRED')
  return lstatSync(path)
}

function readPrivate(path, limit, immutable = false) {
  const before = privatePath(path)
  if (!before.isFile() || before.uid !== process.getuid() || before.nlink !== 1 ||
      ![0o400, ...(immutable ? [] : [0o600])].includes(before.mode & 0o7777) || before.size > limit) fail('PRIVATE_FILE_REQUIRED')
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW)
  try {
    const stat = fstatSync(fd)
    if (stat.dev !== before.dev || stat.ino !== before.ino || stat.size !== before.size) fail('FILE_CHANGED')
    const buffer = Buffer.alloc(stat.size + 1)
    let size = 0, count
    while (size < buffer.length && (count = readSync(fd, buffer, size, buffer.length - size, size))) size += count
    const after = fstatSync(fd), current = privatePath(path)
    if (size !== stat.size || ['dev', 'ino', 'size', 'mtimeMs', 'ctimeMs', 'mode', 'uid', 'nlink'].some(key =>
      stat[key] !== after[key] || stat[key] !== current[key])) fail('FILE_CHANGED')
    return buffer.subarray(0, size)
  } finally { closeSync(fd) }
}

function validatePacket(packet, root) {
  shape(packet, ['packet_id', 'generator_id', 'candidates'])
  identifier(packet.packet_id)
  identifier(packet.generator_id)
  if (!Array.isArray(packet.candidates) || packet.candidates.length > 10) fail('INVALID_CANDIDATES')
  const indices = new Set()
  for (const candidate of packet.candidates) {
    shape(candidate, ['index', 'kind', 'topic', 'statement', 'scope', 'evidence', 'valid_from', 'valid_until'],
      ['index', 'kind', 'topic', 'statement', 'scope', 'evidence', 'valid_from'])
    if (!Number.isSafeInteger(candidate.index) || candidate.index < 0 || indices.has(candidate.index)) fail('INVALID_CANDIDATE_INDEX')
    indices.add(candidate.index)
    if (!['procedure', 'specification'].includes(candidate.kind)) fail('INVALID_KIND')
    text(candidate.topic, 80)
    safeMaterial(candidate.topic)
    text(candidate.statement, 300)
    safeMaterial(candidate.statement)
    if (/(?:[$€£]\s*\d|\b\d+(?:\.\d+)?\s*(?:USD|EUR|GBP|dollars?|\/\s*(?:hr|hour|unit|piece))\b|\b(?:price|cost|rate|margin|markup)\b\s*(?:is|of|:|=)?\s*\d|\b\d+(?:\.\d+)?%\s*(?:margin|markup))/i.test(candidate.statement)) fail('PRICE_OR_RATE_PRESCRIPTION_DENIED')
    shape(candidate.scope, scopeKeys, ['workflow'])
    for (const value of Object.values(candidate.scope)) { text(value); safeMaterial(value) }
    if (candidate.kind === 'specification' && ['customer_id', 'part_no', 'revision'].some(key => !Object.hasOwn(candidate.scope, key))) fail('SPECIFICATION_CONTEXT_REQUIRED')
    date(candidate.valid_from)
    if (Object.hasOwn(candidate, 'valid_until')) {
      date(candidate.valid_until)
      if (candidate.valid_until < candidate.valid_from) fail('INVALID_DATE_RANGE')
    }
    if (!Array.isArray(candidate.evidence) || !candidate.evidence.length || candidate.evidence.length > 5) fail('INVALID_EVIDENCE')
    const sources = new Set()
    for (const evidence of candidate.evidence) {
      shape(evidence, ['path', 'sha256', 'excerpt', 'authority'])
      pathSyntax(evidence.path)
      if (inside(root, evidence.path)) fail('STORE_SOURCE_DENIED')
      safeMaterial(evidence.path)
      if (/(?:^|[/_. -])(?:targets?|oracle|grades?|holdout|scores?)(?:[/_. -]|$)/i.test(evidence.path)) fail('PROHIBITED_EVALUATION_MATERIAL')
      hash(evidence.sha256)
      if (typeof evidence.excerpt !== 'string' || !evidence.excerpt.trim() || evidence.excerpt.length > 1024 || evidence.excerpt.includes('\0')) fail('INVALID_EXCERPT')
      safeMaterial(evidence.excerpt)
      if (!['human', 'document', 'tool_observation'].includes(evidence.authority)) fail('INVALID_AUTHORITY')
      if (sources.has(evidence.path)) fail('DUPLICATE_EVIDENCE')
      sources.add(evidence.path)
    }
  }
}

function verifyEvidence(evidence, copyPath) {
  let bytes
  try { bytes = readPrivate(evidence.path, maxSource) }
  catch { fail('EVIDENCE_UNAVAILABLE') }
  if (sha(bytes) !== evidence.sha256) fail('EVIDENCE_CHANGED')
  if (!bytes.includes(Buffer.from(evidence.excerpt, 'utf8'))) fail('EVIDENCE_EXCERPT_MISSING')
  safeMaterial(bytes.toString('utf8'))
  if (copyPath) {
    let copy
    try { copy = readPrivate(copyPath, maxSource, true) } catch { fail('INTEGRITY_ERROR') }
    if (sha(copy) !== evidence.sha256 || !copy.equals(bytes)) fail('INTEGRITY_ERROR')
  }
  return bytes
}

function attestation(value) {
  shape(value, ['operator', 'reason', 'development_report_sha256', 'confirmation_report_sha256'])
  text(value.operator)
  text(value.reason, 512)
  safeMaterial(value.operator)
  safeMaterial(value.reason)
  hash(value.development_report_sha256)
  hash(value.confirmation_report_sha256)
}

function normalizeReview(packet, packetSha, input) {
  let submitted = null, reviewer = null, failed = false
  const groups = new Map(packet.candidates.map(candidate => [candidate.index, []]))
  try {
    submitted = snapshot(input)
    shape(submitted.value, ['packet_sha256', 'reviewer_id', 'verdicts'])
    const review = submitted.value
    identifier(review.reviewer_id)
    reviewer = review.reviewer_id
    if (review.packet_sha256 !== packetSha || reviewer.toLowerCase() === packet.generator_id.toLowerCase() ||
        !Array.isArray(review.verdicts) || review.verdicts.length > 10 || (!review.verdicts.length && packet.candidates.length)) fail('REVIEW_FAILED')
    for (const verdict of review.verdicts) {
      if (!verdict || !Number.isSafeInteger(verdict.index) || !groups.has(verdict.index)) fail('REVIEW_FAILED')
      groups.get(verdict.index).push(verdict)
    }
  } catch { failed = true }
  const verdicts = packet.candidates.map(candidate => {
    const entries = groups.get(candidate.index)
    let verdict = 'REJECT', reason = 'Review failed; the batch is rejected.'
    if (!failed) {
      reason = 'Missing, duplicate, or malformed verdict; the candidate is rejected.'
      try {
        if (entries.length !== 1) fail('INVALID_VERDICT')
        const entry = shape(entries[0], ['index', 'verdict', 'reason'])
        if (!['ACCEPT', 'REJECT'].includes(entry.verdict)) fail('INVALID_VERDICT')
        text(entry.reason, 512)
        safeMaterial(entry.reason)
        verdict = entry.verdict
        reason = entry.reason
      } catch {}
    }
    return { index: candidate.index, verdict, reason }
  })
  return { packet_id: packet.packet_id, packet_sha256: packetSha, submission_sha256: submitted?.sha256 ?? null,
    reviewer_id: reviewer, failed, verdicts }
}

export class KnowledgeStore {
  #root
  #identity
  #readOnly

  constructor(root, options = {}) {
    shape(options, ['readOnly'], [])
    if (Object.hasOwn(options, 'readOnly') && typeof options.readOnly !== 'boolean') fail('INVALID_SCHEMA')
    this.#root = root
    this.#readOnly = options.readOnly ?? false
    try { this.#identity = privatePath(root, true) } catch (error) {
      if (error.code && !['ENOENT', 'EACCES', 'ENOTDIR'].includes(error.code)) throw error
      fail('PRIVATE_ROOT_REQUIRED')
    }
  }

  #verifyRoot() {
    const stat = privatePath(this.#root, true)
    if (stat.dev !== this.#identity.dev || stat.ino !== this.#identity.ino) fail('ROOT_CHANGED')
  }

  #unlocked() {
    this.#verifyRoot()
    try { lstatSync(join(this.#root, '.writer.lock')); fail('STORE_BUSY') }
    catch (error) { if (error.code !== 'ENOENT') throw error }
  }

  #mutate(fn) {
    if (this.#readOnly) fail('READ_ONLY')
    this.#verifyRoot()
    const lockPath = join(this.#root, '.writer.lock')
    let fd
    try { fd = openSync(lockPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600) }
    catch (error) { fail(error.code === 'EEXIST' ? 'STORE_BUSY' : 'STORAGE_ERROR') }
    const lock = fstatSync(fd)
    try {
      writeFileSync(fd, JSON.stringify({ pid: process.pid, token: randomUUID() }))
      fsyncSync(fd)
      const result = fn(this.#load())
      this.#verifyRoot()
      snapshot(result)
      return result
    } finally {
      closeSync(fd)
      this.#verifyRoot()
      const current = lstatSync(lockPath)
      if (current.dev !== lock.dev || current.ino !== lock.ino) fail('LOCK_CHANGED')
      unlinkSync(lockPath)
    }
  }

  #directories(create = false) {
    const dirs = ['events', 'evidence'].map(name => join(this.#root, name))
    let missing = 0
    for (const dir of dirs) {
      try { privatePath(dir, true) } catch (error) {
        if (error.code !== 'ENOENT') throw error
        missing++
      }
    }
    if (missing && missing !== dirs.length) fail('INTEGRITY_ERROR')
    if (create && missing) for (const dir of dirs) mkdirSync(dir, { mode: 0o700 })
    return missing === 0 || create
  }

  #immutable(path, bytes) {
    const temporary = join(this.#root, `.pending-${randomUUID()}`)
    let fd
    try {
      fd = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o400)
      writeFileSync(fd, bytes)
      fsyncSync(fd)
      closeSync(fd)
      fd = undefined
      linkSync(temporary, path)
    } finally {
      if (fd !== undefined) closeSync(fd)
      unlinkSync(temporary)
    }
    const directory = openSync(dirname(path), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW)
    try { fsyncSync(directory) } finally { closeSync(directory) }
  }

  #append(state, type, data) {
    if (state.count >= maxEvents) fail('STORE_FULL')
    this.#directories(true)
    const event = snapshot({ previous_sha256: state.tail, type, data })
    this.#immutable(join(this.#root, 'events', `${String(state.count + 1).padStart(8, '0')}-${event.sha256}.json`), event.bytes)
    return event.sha256
  }

  #load() {
    const state = { count: 0, tail: null, packets: new Map(), reviews: new Map(), records: new Map(), dispositions: new Set() }
    try {
      if (!this.#directories()) return state
      const files = readdirSync(join(this.#root, 'events')).sort()
      if (files.length > maxEvents) fail('INTEGRITY_ERROR')
      for (const file of files) {
        const match = /^(\d{8})-([a-f0-9]{64})\.json$/.exec(file)
        if (!match || Number(match[1]) !== state.count + 1) fail('INTEGRITY_ERROR')
        const bytes = readPrivate(join(this.#root, 'events', file), maxJson, true)
        if (sha(bytes) !== match[2]) fail('INTEGRITY_ERROR')
        const event = shape(parseJson(bytes), ['previous_sha256', 'type', 'data'])
        if (event.previous_sha256 !== state.tail) fail('INTEGRITY_ERROR')
        const data = event.data, eventSha = match[2]
        if (event.type === 'stage') {
          shape(data, ['packet', 'packet_sha256'])
          validatePacket(data.packet, this.#root)
          if (snapshot(data.packet).sha256 !== data.packet_sha256 || state.packets.has(data.packet.packet_id)) fail('INTEGRITY_ERROR')
          state.packets.set(data.packet.packet_id, data)
        } else if (event.type === 'review') {
          shape(data, ['packet_id', 'packet_sha256', 'submission_sha256', 'reviewer_id', 'failed', 'verdicts'])
          const staged = state.packets.get(data.packet_id)
          if (!staged || staged.packet_sha256 !== data.packet_sha256 || state.reviews.has(data.packet_id) || typeof data.failed !== 'boolean') fail('INTEGRITY_ERROR')
          if (data.submission_sha256 !== null) hash(data.submission_sha256)
          if (data.reviewer_id !== null) identifier(data.reviewer_id)
          if (!data.failed && (!data.reviewer_id || data.reviewer_id.toLowerCase() === staged.packet.generator_id.toLowerCase())) fail('INTEGRITY_ERROR')
          if (!Array.isArray(data.verdicts) || data.verdicts.length !== staged.packet.candidates.length) fail('INTEGRITY_ERROR')
          data.verdicts.forEach((verdict, i) => {
            shape(verdict, ['index', 'verdict', 'reason'])
            text(verdict.reason, 512)
            safeMaterial(verdict.reason)
            if (verdict.index !== staged.packet.candidates[i].index || !['ACCEPT', 'REJECT'].includes(verdict.verdict) || (data.failed && verdict.verdict !== 'REJECT')) fail('INTEGRITY_ERROR')
          })
          state.reviews.set(data.packet_id, { ...data, review_sha256: eventSha })
        } else if (['activate', 'duplicate'].includes(event.type)) {
          shape(data, ['packet_id', 'packet_sha256', 'review_sha256', 'candidate_index', 'operator_attestation', ...(event.type === 'duplicate' ? ['existing_record_id', 'disposition'] : [])])
          const staged = state.packets.get(data.packet_id), review = state.reviews.get(data.packet_id)
          const candidate = staged?.packet.candidates.find(item => item.index === data.candidate_index)
          const key = encode([data.packet_id, data.candidate_index])
          attestation(data.operator_attestation)
          if (!candidate || data.packet_sha256 !== staged.packet_sha256 || data.review_sha256 !== review?.review_sha256 ||
              review.verdicts.find(item => item.index === candidate.index)?.verdict !== 'ACCEPT' || state.dispositions.has(key)) fail('INTEGRITY_ERROR')
          const scoped = [...state.records.values()].filter(record => record.status === 'ACTIVE' && encode(record.candidate.scope) === encode(candidate.scope))
          const existing = scoped.find(record => record.candidate.statement === candidate.statement)
          if (event.type === 'activate') {
            if (existing || scoped.some(record => record.candidate.kind === candidate.kind && record.candidate.topic === candidate.topic)) fail('INTEGRITY_ERROR')
            state.records.set(eventSha, { record_id: eventSha, record_sha256: eventSha, ...data, candidate, status: 'ACTIVE' })
          } else if (!existing || existing.record_id !== data.existing_record_id || existing.candidate.statement !== candidate.statement || data.disposition !== 'KEEP_EXISTING_REJECT_REDUNDANT') fail('INTEGRITY_ERROR')
          state.dispositions.add(key)
        } else if (event.type === 'retire') {
          shape(data, ['record_id', 'record_sha256', 'reason'])
          text(data.reason, 512)
          safeMaterial(data.reason)
          const record = state.records.get(data.record_id)
          if (!record || record.record_sha256 !== data.record_sha256 || record.status !== 'ACTIVE') fail('INTEGRITY_ERROR')
          record.status = 'RETIRED'
        } else fail('INTEGRITY_ERROR')
        state.count++
        state.tail = eventSha
      }
      return state
    } catch { fail('INTEGRITY_ERROR') }
  }

  stage(packet) {
    const submitted = snapshot(packet)
    validatePacket(submitted.value, this.#root)
    return this.#mutate(state => {
      const previous = state.packets.get(submitted.value.packet_id)
      if (previous && previous.packet_sha256 !== submitted.sha256) fail('PACKET_ID_CONFLICT')
      const sources = submitted.value.candidates.flatMap(candidate => candidate.evidence).map(evidence => ({
        evidence, bytes: verifyEvidence(evidence, previous ? join(this.#root, 'evidence', `${evidence.sha256}.bin`) : undefined),
      }))
      if (!previous) {
        if (state.count >= maxEvents) fail('STORE_FULL')
        this.#directories(true)
        for (const { evidence, bytes } of sources) {
          const path = join(this.#root, 'evidence', `${evidence.sha256}.bin`)
          try {
            const copy = readPrivate(path, maxSource, true)
            if (!copy.equals(bytes)) fail('INTEGRITY_ERROR')
          } catch (error) {
            if (error.code !== 'ENOENT') throw error
            this.#immutable(path, bytes)
          }
        }
        this.#append(state, 'stage', { packet: submitted.value, packet_sha256: submitted.sha256 })
      }
      return { packet_id: submitted.value.packet_id, packet_sha256: submitted.sha256, status: 'STAGED',
        candidate_count: submitted.value.candidates.length, idempotent: Boolean(previous) }
    })
  }

  review(packetId, verdicts) {
    identifier(packetId)
    return this.#mutate(state => {
      const staged = state.packets.get(packetId)
      if (!staged) fail('PACKET_NOT_FOUND')
      if (state.reviews.has(packetId)) fail('REVIEW_ALREADY_RECORDED')
      let result = normalizeReview(staged.packet, staged.packet_sha256, verdicts)
      try {
        for (const evidence of staged.packet.candidates.flatMap(candidate => candidate.evidence)) {
          verifyEvidence(evidence, join(this.#root, 'evidence', `${evidence.sha256}.bin`))
        }
      } catch {
        result = { ...result, failed: true, verdicts: staged.packet.candidates.map(candidate => ({
          index: candidate.index, verdict: 'REJECT', reason: 'Evidence revalidation failed; the batch is rejected.',
        })) }
      }
      const reviewSha = this.#append(state, 'review', result)
      return { ...result, review_sha256: reviewSha, status: result.failed ? 'REVIEW_FAILED' : 'REVIEWED' }
    })
  }

  activate(packetId, candidateIndex, operatorAttestation) {
    identifier(packetId)
    if (!Number.isSafeInteger(candidateIndex) || candidateIndex < 0) fail('INVALID_CANDIDATE_INDEX')
    const operator = snapshot(operatorAttestation).value
    attestation(operator)
    return this.#mutate(state => {
      const staged = state.packets.get(packetId), review = state.reviews.get(packetId)
      if (!staged) fail('PACKET_NOT_FOUND')
      const candidate = staged.packet.candidates.find(item => item.index === candidateIndex)
      if (!candidate) fail('INVALID_CANDIDATE_INDEX')
      if (!review) fail('REVIEW_REQUIRED')
      if (review.verdicts.find(item => item.index === candidateIndex)?.verdict !== 'ACCEPT') fail('CANDIDATE_REJECTED')
      if (state.dispositions.has(encode([packetId, candidateIndex]))) fail('CANDIDATE_ALREADY_DISPOSED')
      for (const evidence of candidate.evidence) verifyEvidence(evidence, join(this.#root, 'evidence', `${evidence.sha256}.bin`))
      const data = { packet_id: packetId, packet_sha256: staged.packet_sha256, review_sha256: review.review_sha256,
        candidate_index: candidateIndex, operator_attestation: operator }
      const scoped = [...state.records.values()].filter(record => record.status === 'ACTIVE' && encode(record.candidate.scope) === encode(candidate.scope))
      const existing = scoped.find(record => record.candidate.statement === candidate.statement)
      if (existing) {
        const disposition = 'KEEP_EXISTING_REJECT_REDUNDANT'
        const dispositionSha = this.#append(state, 'duplicate', { ...data, existing_record_id: existing.record_id, disposition })
        return { ...data, status: 'DUPLICATE_REJECTED', disposition, record_id: existing.record_id,
          record_sha256: existing.record_sha256, disposition_sha256: dispositionSha }
      }
      if (scoped.some(record => record.candidate.kind === candidate.kind && record.candidate.topic === candidate.topic)) fail('ACTIVE_SCOPE_CONFLICT')
      const recordSha = this.#append(state, 'activate', data)
      return { ...data, status: 'ACTIVE', record_id: recordSha, record_sha256: recordSha }
    })
  }

  search(query) {
    const input = snapshot(query).value
    shape(input, [...scopeKeys, 'as_of', 'limit'], ['workflow', 'as_of'])
    for (const key of scopeKeys) if (Object.hasOwn(input, key)) { text(input[key]); safeMaterial(input[key]) }
    date(input.as_of)
    const limit = input.limit ?? 10
    if (!Number.isInteger(limit) || limit < 1 || limit > 10) fail('INVALID_LIMIT')
    this.#unlocked()
    const state = this.#load(), records = []
    const matches = [...state.records.values()].filter(record => {
      const candidate = record.candidate
      return record.status === 'ACTIVE' && candidate.valid_from <= input.as_of &&
        (!candidate.valid_until || candidate.valid_until >= input.as_of) &&
        Object.entries(candidate.scope).every(([key, value]) => input[key] === value)
    }).sort((a, b) => Object.keys(b.candidate.scope).length - Object.keys(a.candidate.scope).length ||
      b.candidate.valid_from.localeCompare(a.candidate.valid_from) || a.record_id.localeCompare(b.record_id))
    for (const record of matches.slice(0, limit)) {
      const candidate = record.candidate
      const evidence = candidate.evidence.map(item => {
        const copiedPath = join(this.#root, 'evidence', `${item.sha256}.bin`)
        verifyEvidence(item, copiedPath)
        return { ...item, copied_path: copiedPath }
      })
      records.push({ record_id: record.record_id, record_sha256: record.record_sha256, packet_id: record.packet_id,
        packet_sha256: record.packet_sha256, review_sha256: record.review_sha256, candidate_index: candidate.index,
        kind: candidate.kind, topic: candidate.topic, statement: candidate.statement, scope: candidate.scope, evidence,
        valid_from: candidate.valid_from, ...(candidate.valid_until ? { valid_until: candidate.valid_until } : {}),
        status: 'ACTIVE', operator_attestation: record.operator_attestation })
    }
    const result = { records, as_of: input.as_of, limit, usage: 'reference_only', blind_safety: 'NOT_ATTESTED' }
    snapshot(result)
    this.#unlocked()
    return result
  }

  retire(recordId, reason) {
    hash(recordId)
    text(reason, 512)
    safeMaterial(reason)
    return this.#mutate(state => {
      const record = state.records.get(recordId)
      if (!record) fail('RECORD_NOT_FOUND')
      if (record.status !== 'ACTIVE') fail('RECORD_ALREADY_RETIRED')
      const retirementSha = this.#append(state, 'retire', { record_id: recordId, record_sha256: record.record_sha256, reason })
      return { record_id: recordId, record_sha256: record.record_sha256, status: 'RETIRED', reason, retirement_sha256: retirementSha }
    })
  }
}

async function cli() {
  try {
    const [action, flag, root, ...rest] = process.argv.slice(2)
    if (!['stage', 'review', 'activate', 'search', 'retire'].includes(action) || flag !== '--root' || !root || rest.length) fail('INVALID_ARGUMENTS')
    const chunks = []
    let size = 0
    for await (const chunk of process.stdin) {
      size += chunk.length
      if (size > maxJson) fail('INPUT_TOO_LARGE')
      chunks.push(chunk)
    }
    const input = parseJson(Buffer.concat(chunks))
    const store = new KnowledgeStore(root, { readOnly: action === 'search' })
    let result
    if (action === 'stage') result = store.stage(input)
    if (action === 'search') result = store.search(input)
    if (action === 'review') {
      shape(input, ['packet_id', 'review'])
      result = store.review(input.packet_id, input.review)
    }
    if (action === 'activate') {
      shape(input, ['packet_id', 'candidate_index', 'operator_attestation'])
      result = store.activate(input.packet_id, input.candidate_index, input.operator_attestation)
    }
    if (action === 'retire') {
      shape(input, ['record_id', 'reason'])
      result = store.retire(input.record_id, input.reason)
    }
    const output = snapshot({ ok: true, result }).bytes
    if (output.length + 1 > maxJson) fail('OUTPUT_TOO_LARGE')
    process.stdout.write(`${output.toString('utf8')}\n`)
  } catch (error) {
    const code = /^[A-Z_]+$/.test(error.code ?? '') ? error.code : 'STORAGE_ERROR'
    process.stdout.write(`${JSON.stringify({ ok: false, error: { code } })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await cli()
