import { readFileSync } from 'node:fs'
import { assertOrderRequest } from '../../estimator/src/order.ts'

try {
  assertOrderRequest(JSON.parse(readFileSync(process.argv[2]!, 'utf8')))
} catch {
  process.exitCode = 1
}
