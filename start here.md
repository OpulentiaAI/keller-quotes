# C. Keller Mfg. evidence workspace

Begin at the [[source-catalog]] to distinguish internal calculations, issued customer quote letters, private originals, and audit gaps. [[organization-catalog]] explains who owns price review and release. The five canonical Keller skills are in `.agents/skills/`; typed wrappers in `skills/` make them discoverable to the agent session without maintaining duplicate procedures.

The default [[Keller Codex]] profile exposes graph reads, bounded `keller_polygres` and `keller_sources` evidence readers, and `keller_quote` for an internal offline order draft; it does not expose native shell or arbitrary writes. The draft tool needs an explicit approved corpus, JSON order request, and named reviewer. Its returned order, Markdown, review, and private artifact references are internal only: no automatic approval, customer delivery, or ≥90% completion claim follows. See [[arsumbris-workspace]] for local bindings, launch, verification, and known gaps.
