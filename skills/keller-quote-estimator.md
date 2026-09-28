---
type: mcp.skill::au-mcp-sdk
name: keller-quote-estimator
description: Use for a Keller RFQ or complete priced-order proposal, with historical analog review, explicit current cost inputs, held lines, and named human approval.
---

# Keller quote and order drafts

Read `.agents/skills/keller-quote-estimator/SKILL.md` in the `keller-quotes` workspace through the pinned read gate before pricing. That file is the **only** maintained procedure; this typed node is a discovery and launch-time wrapper, not a second copy. Read its linked quote-register and Polygres skills as needed. If the canonical file cannot be read, stop rather than estimate from this summary.

Choose an explicit, verified price basis and preserve its source hashes. Missing revision, UOM, material, current costs, or a reliable analog means a held line, not an invented price. In `Keller Codex`, `keller_sources` can inspect bound originals read-only and `keller_quote` runs the offline internal order CLI against an explicit customer-PDF corpus with a named reviewer. Its structured order, Markdown, review, and artifact references are private and require human review; neither `BLOCKED` nor `PRICED_REQUIRES_REVIEW` authorizes customer release. The canonical standalone CLI remains an alternative for an approved private operator environment.
