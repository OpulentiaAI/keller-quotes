#!/usr/bin/env node
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mcpConfig } from './arsumbris-mcp-config.mjs'
import { options, requireRuntime, requireWorkspace } from './arsumbris-runtime.mjs'

const args = process.argv.slice(2)
const skipCorpora = args.includes('--skip-corpora')

function payload(result) {
  if (result.isError) throw new Error('MCP tool returned an error')
  const text = result.content?.find(item => item.type === 'text')?.text
  if (typeof text !== 'string') throw new Error('MCP tool returned no text')
  return JSON.parse(text)
}

try {
  const { workspace, runtimeRoot } = options(args.filter(arg => arg !== '--skip-corpora'))
  const entry = requireWorkspace(workspace)
  const runtime = requireRuntime(runtimeRoot)
  const config = JSON.parse(readFileSync(join(entry, '.keller-local/arsumbris/mcp.json'), 'utf8'))
  const expected = mcpConfig(entry, runtime)
  if (JSON.stringify(config) !== JSON.stringify(expected)) throw new Error('MCP config differs from this workspace/runtime; regenerate deliberately')
  const sdkRoot = join(runtime, 'au-mcp-adapter-cc/node_modules/@modelcontextprotocol/sdk/dist/esm/client')
  const { Client } = await import(pathToFileURL(join(sdkRoot, 'index.js')).href)
  const { StdioClientTransport } = await import(pathToFileURL(join(sdkRoot, 'stdio.js')).href)
  const expectedTools = {
    'keller-ars-readonly': ['au_diagnostics', 'au_files', 'au_follow', 'au_instances_of', 'au_members', 'au_resolved', 'au_type', 'read_file_pinned'],
    'keller-polygres-readonly': ['keller_polygres'],
  }
  const summary = {}
  for (const [name, spec] of Object.entries(config.mcpServers)) {
    const transport = new StdioClientTransport({ command: spec.command, args: spec.args,
      env: { PATH: process.env.PATH, HOME: process.env.HOME } })
    const client = new Client({ name: 'keller-readonly-smoke', version: '0' })
    try {
      await client.connect(transport)
      const actual = (await client.listTools()).tools.map(tool => tool.name).sort()
      if (JSON.stringify(actual) !== JSON.stringify(expectedTools[name])) throw new Error(`Unexpected tools for ${name}: ${actual.join(', ')}`)
      summary[name] = { tools: actual.length }
      if (name === 'keller-ars-readonly') {
        const result = payload(await client.callTool({ name: 'au_diagnostics', arguments: { limit: 1 } }))
        if (!Number.isInteger(result.summary?.total)) throw new Error('Invalid graph diagnostic count')
        if (result.summary.total !== 0) throw new Error('Typed workspace has unresolved graph errors')
        summary[name].diagnostics = result.summary.total
      } else if (!skipCorpora) {
        const result = payload(await client.callTool({ name: 'keller_polygres', arguments: { action: 'corpora' } }))
        if (!Array.isArray(result.corpora)) throw new Error('Invalid Polygres corpora response')
        summary[name].corpora = result.corpora.length
        summary[name].documents = result.corpora.reduce((sum, row) => sum + Number(row.documents ?? 0), 0)
      }
    } finally {
      await client.close()
    }
  }
  console.log(JSON.stringify(summary))
} catch (error) {
  console.error(`Ars MCP smoke failed: ${error.message}`)
  process.exitCode = 1
}
