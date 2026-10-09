import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import type { CallableResult, PluginContext, PluginRuntime } from '@arsumbris/au-mcp-sdk'

const reader = fileURLToPath(new URL('./read.py', import.meta.url))

export function createPlugin(_ctx: PluginContext): PluginRuntime {
  return {
    invoke(input: unknown): Promise<CallableResult> {
      return new Promise((resolve) => {
        const child = execFile(process.env.KELLER_PYTHON || 'python3', [reader], {
          timeout: 45000, maxBuffer: 64 * 1024,
          env: {
            PATH: process.env.PATH, LANG: process.env.LANG,
            KELLER_MARKET_ENABLED: process.env.KELLER_MARKET_ENABLED,
            EXA_API_KEY: process.env.EXA_API_KEY,
            FASTMARKETS_ACCESS_TOKEN: process.env.FASTMARKETS_ACCESS_TOKEN,
            KELLER_FASTMARKETS_LICENSED: process.env.KELLER_FASTMARKETS_LICENSED,
          },
        }, (error, stdout) => {
          if (error) {
            resolve({ content: { error: 'Market lookup unavailable or timed out' }, isError: true })
            return
          }
          try {
            const result = JSON.parse(stdout)
            resolve({ content: result, isError: Boolean(result.error) || result.status === 'unavailable' })
          } catch {
            resolve({ content: { error: 'Invalid market lookup response' }, isError: true })
          }
        })
        child.stdin?.on('error', () => {})
        child.stdin?.end(JSON.stringify(input ?? {}))
      })
    },
  }
}
