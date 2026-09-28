import { execFile } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { chmodSync, existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { CallableResult, PluginContext, PluginRuntime } from '@arsumbris/au-mcp-sdk'

const run = promisify(execFile)
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const privateRoot = join(homedir(), '.local/share/keller-quotes/drafts')
const tsx = join(root, 'estimator/node_modules/tsx/dist/cli.mjs')
const python = process.env.KELLER_PYTHON || 'python3'
const warning = 'INTERNAL DRAFT ONLY: named human review required; no customer release. Customer-PDF historical quoted prices have unknown outcome and are nominal as-quoted dollars, not current material/labor costs or a validated 90% accuracy claim. Operator amounts/costs are proposals, not verified live costs.'

function privateDirectory(): void {
  for (const path of [join(homedir(), '.local'), join(homedir(), '.local/share'),
    join(homedir(), '.local/share/keller-quotes'), privateRoot]) {
    if (!existsSync(path)) mkdirSync(path, { mode: 0o700 })
    const stat = lstatSync(path)
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid?.() ||
        ((path === privateRoot || path === dirname(privateRoot)) && (stat.mode & 0o077) !== 0) ||
        realpathSync(path) !== path) throw new Error('private draft storage unavailable')
  }
}

function childEnvironment(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const key of ['HOME', 'PATH', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR']) {
    if (process.env[key] !== undefined) env[key] = process.env[key]
  }
  return env
}

function valid(input: unknown): input is { corpus: string; request: string; reviewer: string } {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return false
  const value = input as Record<string, unknown>
  return Object.keys(value).every(key => ['corpus', 'request', 'reviewer'].includes(key)) &&
    typeof value.corpus === 'string' && /^[a-f0-9]{64}$/.test(value.corpus) &&
    typeof value.request === 'string' && value.request.length > 0 && Buffer.byteLength(value.request) <= 128 * 1024 &&
    typeof value.reviewer === 'string' && value.reviewer.trim().length > 0 && value.reviewer.length <= 120 &&
    !/[\x00-\x1f\x7f]/.test(value.reviewer)
}

export function createPlugin(_ctx: PluginContext): PluginRuntime {
  return {
    async invoke(input: unknown): Promise<CallableResult> {
      if (!valid(input)) return { content: { error: 'Explicit corpus, OrderRequest JSON and named reviewer are required' }, isError: true }
      let request: unknown
      try {
        request = JSON.parse(input.request)
        if (!request || typeof request !== 'object' || Array.isArray(request) ||
            !Array.isArray((request as { parts?: unknown }).parts) || (request as { parts: unknown[] }).parts.length > 50) {
          throw new Error('invalid request')
        }
      } catch {
        return { content: { error: 'Invalid OrderRequest JSON (maximum 50 parts)' }, isError: true }
      }
      if (!process.env.POLYGRES_DIRECT_URL) return { content: { error: 'Polygres read access is not configured' }, isError: true }
      let draft: string | undefined
      try {
        privateDirectory()
        const id = randomUUID()
        draft = join(privateRoot, id)
        mkdirSync(draft, { mode: 0o700 })
        chmodSync(draft, 0o700)
        const requestPath = join(draft, 'request.json')
        const csvPath = join(draft, 'corpus.csv')
        const out = join(draft, 'output')
        writeFileSync(requestPath, JSON.stringify(request), { flag: 'wx', mode: 0o600 })
        const childEnv = childEnvironment()
        await run(process.execPath, [tsx, join(root, 'arsumbris/quote/validate.ts'), requestPath], {
          cwd: root, env: childEnv, timeout: 15000, maxBuffer: 1024,
        })
        const { stdout } = await run(python, [join(root, 'arsumbris/quote/export.py'), input.corpus, csvPath], {
          cwd: root, env: { ...childEnv, POLYGRES_DIRECT_URL: process.env.POLYGRES_DIRECT_URL },
          timeout: 180000, maxBuffer: 4096,
        })
        const exported = JSON.parse(stdout) as { sha256?: string; rows?: number }
        const csvStat = lstatSync(csvPath)
        if (!csvStat.isFile() || csvStat.isSymbolicLink() || csvStat.uid !== process.getuid?.() ||
            (csvStat.mode & 0o777) !== 0o600) throw new Error('invalid private corpus export')
        const corpusSha = createHash('sha256').update(readFileSync(csvPath)).digest('hex')
        if (exported.sha256 !== corpusSha || !Number.isSafeInteger(exported.rows)) throw new Error('invalid export proof')
        try {
          await run(process.execPath, [tsx, join(root, 'estimator/src/order-cli.ts'), requestPath,
            '--register', csvPath, '--out', out], { cwd: root, env: childEnv, timeout: 180000, maxBuffer: 4096 })
        } catch (error) {
          if ((error as { code?: number }).code !== 3) throw error
        }
        const jsonPath = join(out, 'order.json')
        const markdownPath = join(out, 'order.md')
        const order = JSON.parse(readFileSync(jsonPath, 'utf8')) as {
          state: string; total: number | null; blockers: string[]; requires_human_review: boolean;
          provenance: { register_sha256: string; request_sha256: string; mode: string };
          lines: { pricing_source: string }[];
        }
        if (!['BLOCKED', 'PRICED_REQUIRES_REVIEW'].includes(order.state) || order.requires_human_review !== true ||
            order.provenance.register_sha256 !== corpusSha || order.provenance.mode !== 'offline' ||
            (order.state === 'BLOCKED' && order.total !== null)) throw new Error('invalid draft result')
        chmodSync(jsonPath, 0o600)
        chmodSync(markdownPath, 0o600)
        const reviewPath = join(out, 'review.json')
        writeFileSync(reviewPath, JSON.stringify({
          status: 'PENDING_NAMED_HUMAN_REVIEW', reviewer: input.reviewer.trim(),
          requires_human_review: true, customer_release_authorized: false, state: order.state,
          corpus_id: input.corpus, corpus_sha256: corpusSha, request_sha256: order.provenance.request_sha256,
          warning,
        }, null, 2) + '\n', { flag: 'wx', mode: 0o600 })
        const markdown = readFileSync(markdownPath, 'utf8')
        const review = JSON.parse(readFileSync(reviewPath, 'utf8'))
        if (Buffer.byteLength(JSON.stringify({ order, markdown, review })) > 4 * 1024 * 1024) {
          throw new Error('draft exceeds bounded result size')
        }
        return { content: {
          draft_id: id, state: order.state, review_status: 'PENDING_NAMED_HUMAN_REVIEW', reviewer: input.reviewer.trim(),
          requires_human_review: true, total: order.total, blockers: order.blockers,
          order, markdown, review,
          price_bases: [...new Set(order.lines.map(line => line.pricing_source))],
          warning, corpus_id: input.corpus, corpus_sha256: corpusSha, source_rows: exported.rows,
          request_sha256: order.provenance.request_sha256,
          artifacts: { order_json: `quote-draft:${id}/order.json`, order_markdown: `quote-draft:${id}/order.md`,
            review_json: `quote-draft:${id}/review.json` },
        } }
      } catch {
        if (draft) rmSync(draft, { recursive: true, force: true })
        return { content: { error: 'Invalid request or verified offline draft unavailable; no quote was released' }, isError: true }
      }
    },
  }
}
