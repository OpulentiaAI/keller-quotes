import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import type { PluginContext, PluginRuntime, CallableResult } from '@arsumbris/au-mcp-sdk'

const reader = fileURLToPath(new URL('./read.py', import.meta.url))

export function createPlugin(_ctx: PluginContext): PluginRuntime {
  return {
    invoke(input: unknown): Promise<CallableResult> {
      const python = process.env.KELLER_PYTHON || 'python3'
      if (!process.env.POLYGRES_DIRECT_URL) {
        return Promise.resolve({ content: { error: 'Polygres access is not configured' }, isError: true })
      }
      const env = {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        LANG: process.env.LANG,
        LC_ALL: process.env.LC_ALL,
        LC_CTYPE: process.env.LC_CTYPE,
        POLYGRES_DIRECT_URL: process.env.POLYGRES_DIRECT_URL,
      }
      return new Promise((resolve) => {
        const child = execFile(python, [reader], { timeout: 12000, maxBuffer: 512 * 1024, env }, (error, stdout) => {
          if (error) {
            resolve({ content: { error: 'Polygres read unavailable or timed out' }, isError: true })
            return
          }
          try {
            const result = JSON.parse(stdout)
            resolve(result.error ? { content: result, isError: true } : { content: result })
          } catch {
            resolve({ content: { error: 'Polygres read returned an invalid response' }, isError: true })
          }
        })
        child.stdin?.on('error', () => {})
        child.stdin?.end(JSON.stringify(input ?? {}))
      })
    },
  }
}
