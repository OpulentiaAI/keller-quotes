import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import { prepareHostEngine } from '../start-arsumbris.mjs'

function fixture(probes, pid = null) {
  const child = new EventEmitter()
  const killed = []
  const spawned = []
  child.kill = signal => { killed.push(signal) }
  let elapsed = 0
  let lastProbe = null
  return {
    child, killed, spawned,
    options: {
      entry: '/workspace/entry', binary: '/runtime/au', env: { PATH: '/bin' },
      sdk: {
        probeReady: async () => { if (probes.length) lastProbe = probes.shift(); return lastProbe },
        readDaemonPid: () => pid,
        pidAlive: candidate => candidate === pid,
      },
      spawnChild: (...args) => { spawned.push(args); return child },
      wait: async ms => { elapsed += ms },
      now: () => elapsed,
      timeoutMs: 120_000,
    },
  }
}

test('cold host startup waits beyond the renderer deadline for the complete native graph', async () => {
  const run = fixture([null, ...Array(40).fill(null), { ready: false }, { ready: true }])
  assert.equal(await prepareHostEngine(run.options), run.child)
  assert.equal(run.spawned.length, 1)
  assert.deepEqual(run.spawned[0], ['/runtime/au', ['daemon', 'start', '/workspace/entry'], { cwd: '/workspace/entry', stdio: 'inherit', env: { PATH: '/bin' } }])
  assert.deepEqual(run.killed, [])
})

test('an already ready engine is reused without taking ownership', async () => {
  const run = fixture([{ ready: true }], 42)
  assert.equal(await prepareHostEngine(run.options), null)
  assert.deepEqual(run.spawned, [])
  assert.deepEqual(run.killed, [])
})

test('a foreign cold-starting engine is waited for without spawning or killing it', async () => {
  const run = fixture([null, null, { ready: false }, { ready: true }], 42)
  assert.equal(await prepareHostEngine(run.options), null)
  assert.deepEqual(run.spawned, [])
  assert.deepEqual(run.killed, [])
})

test('a reachable engine that is still deriving is not duplicated', async () => {
  const run = fixture([{ ready: false }, { ready: false }, { ready: true }])
  assert.equal(await prepareHostEngine(run.options), null)
  assert.deepEqual(run.spawned, [])
})

test('a stuck owned engine is bounded and stopped before a host can launch', async () => {
  const run = fixture([null])
  await assert.rejects(prepareHostEngine(run.options), /within 120s; host not launched/)
  assert.equal(run.spawned.length, 1)
  assert.deepEqual(run.killed, ['SIGTERM'])
})

test('a stuck foreign engine is not killed on timeout', async () => {
  const run = fixture([null], 42)
  await assert.rejects(prepareHostEngine(run.options), /host not launched/)
  assert.deepEqual(run.spawned, [])
  assert.deepEqual(run.killed, [])
})

test('owned spawn failures and early exits prevent host startup', async () => {
  for (const event of ['error', 'exit']) {
    const run = fixture([null])
    run.options.wait = async () => {
      if (event === 'error') run.child.emit('error', new Error('not executable'))
      else run.child.emit('exit', 7, null)
    }
    await assert.rejects(prepareHostEngine(run.options), event === 'error' ? /not executable/ : /Engine exited before readiness \(7\)/)
    assert.deepEqual(run.killed, ['SIGTERM'])
  }
})

test('cancelling readiness stops only the owned engine and removes signal handlers', async () => {
  const before = process.listenerCount('SIGINT')
  const run = fixture([null])
  run.options.wait = async () => { process.emit('SIGINT') }
  await assert.rejects(prepareHostEngine(run.options), /cancelled/)
  assert.equal(process.listenerCount('SIGINT'), before)
  assert.deepEqual(run.killed, ['SIGINT', 'SIGTERM'])
})
