import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

export function mcpConfig(workspace, runtimeRoot, node = process.execPath) {
  const entry = profile => ({
    command: node,
    args: [join(workspace, 'scripts/start-arsumbris-mcp-client.mjs'), '--workspace', workspace,
      '--runtime-root', runtimeRoot, '--profile', profile],
  })
  return { mcpServers: {
    'keller-ars-readonly': entry('Keller Graph Readonly'),
    'keller-polygres-readonly': entry('Keller Polygres Readonly'),
  } }
}

export function saveMcpConfig(workspace, runtimeRoot, node = process.execPath) {
  const path = join(workspace, '.keller-local/arsumbris/mcp.json')
  const content = `${JSON.stringify(mcpConfig(workspace, runtimeRoot, node), null, 2)}\n`
  if (existsSync(path)) {
    if (readFileSync(path, 'utf8') !== content) throw new Error(`Existing MCP client config differs; preserving user file: ${path}`)
    return path
  }
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, content, { flag: 'wx', mode: 0o600 })
  return path
}
