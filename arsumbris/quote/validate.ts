import { readFileSync } from 'node:fs'
import { assertOrderRequest, requiresHistoricalRegister } from '../../estimator/src/order.ts'

import { verifyRetainedIntake } from '../../estimator/src/intake.ts'

try {
  const request = JSON.parse(readFileSync(process.argv[2]!, 'utf8'))
  assertOrderRequest(request)
  verifyRetainedIntake(request)
  const requires_register = requiresHistoricalRegister(request)
  console.log(JSON.stringify({ requires_register }))
} catch {
  process.exitCode = 1
}
