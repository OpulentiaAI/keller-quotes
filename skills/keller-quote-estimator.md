---
type: mcp.skill::au-mcp-sdk
name: keller-quote-estimator
description: Use for a Keller RFQ or priced-order proposal with retained evidence, supported estimates, distinct proposal/adoption decisions and named human approval.
---

# Keller quote and order drafts

Read `.agents/skills/keller-quote-estimator/SKILL.md` in the `keller-quotes` workspace through the pinned read gate before pricing. That file is the **only** maintained procedure; this typed node is a discovery and launch-time wrapper, not a second copy. Read its linked quote-register and Polygres skills as needed. If the canonical file cannot be read, stop rather than estimate from this summary.

Choose an explicit price basis; intake all lines, draft once, inspect contributors, then perform one deduplicated exact evidence phase with bounded continuations for named price-critical gaps. Preserve finite backend proposals even when adoption is declined. Explicit incompatibility blocks transfer; unknown current cost blocks a supported margin claim, not historical comparison; unverified actual-job ledgers do not block a supported prospective estimate. Ask one consolidated follow-up only after available relevant evidence is exhausted. In `Keller Codex`, `keller_quote` is offline; richer `keller_sources` access is operator-only where authorized, never a scope bypass. Keep all outputs private for independent challenge and named human review; neither `BLOCKED` nor `PRICED_REQUIRES_REVIEW` authorizes release. The canonical standalone CLI remains an approved operator alternative.
