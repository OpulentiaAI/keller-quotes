---
type: mcp.skill::au-mcp-sdk
name: keller-estimator-evals
description: Use when evaluating Keller estimator retrieval or pricing with cutoff-aware leave-one-out replay and honest held-line/error reporting.
---

# Evaluate the Keller estimator

Read `.agents/skills/keller-estimator-evals/SKILL.md` in `keller-quotes` through the pinned read gate. Its commands, case manifests, comparison constraints, and provenance are authoritative. If unavailable, do not report an accuracy result. The `keller_quote` draft tool and `keller_sources` reader do not run evals; historical replay on internal calculation targets is not a completed-quoting success metric and cannot be compared with customer-PDF targets as if the estimator improved.
