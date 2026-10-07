# Git-linked Keller work and operator evidence

Git tracks the code, native typed findings and the retrieval/checksum registry for the private evidence archive.
The archive assets belong to this same private GitHub repository, require repository access and remain outside the working checkout.
An authenticated operator can recover the retained files without depending on the original agent machine.
This is preservation and access, not a new source assessment, independent business review or pricing activation.

## Code and typed findings

The [typed findings checkpoint](https://github.com/OpulentiaAI/keller-quotes/commit/68c82010174b66e7a5abe2ed255d86130a59dc5e) is the archive's fixed Git anchor.
Start with [[map - Keller operator findings]] and [[Keller Git delivery and private artifact access 2026-10-07]].

The pending implementations are already pushed and inspectable; the table records their observed heads on 2026-10-07, not promises about later branch state.

| Implementation | Git checkpoint | Review and dependency |
|---|---|---|
| Jev fallback boundaries and part-number retrieval | [`eb4c74e`](https://github.com/OpulentiaAI/keller-quotes/commit/eb4c74eeb8f2ea6ebefda1a194fb256bed0e7dd8) | [PR 24](https://github.com/OpulentiaAI/keller-quotes/pull/24), targeting `main` |
| Guarded learning environment, feedback and knowledge lifecycle | [`09f3d67`](https://github.com/OpulentiaAI/keller-quotes/commit/09f3d678522de34c701c8bb9e12b5bca502fd4d8) | [PR 25](https://github.com/OpulentiaAI/keller-quotes/pull/25), targeting PR 24's branch |
| Source-bound assessment, full-data audit and scoped analog identity | [`cf1ee17`](https://github.com/OpulentiaAI/keller-quotes/commit/cf1ee175f9789ed707190ee13ca7e734f7c32a1a) | [PR 26](https://github.com/OpulentiaAI/keller-quotes/pull/26), targeting PR 25's branch |

For a separate inspection checkout without changing the current branch:

```bash
git fetch origin opulent/usable-analog-screening
git worktree add --detach ../keller-assessment-inspection cf1ee175f9789ed707190ee13ca7e734f7c32a1a
```

Accessibility does not merge these branches, promote the candidate's failed historical comparison or authorize customer delivery.
Review and activation remain separate decisions.

## Download and recover the private archive

The [operator archive](https://github.com/OpulentiaAI/keller-quotes/releases/tag/keller-operator-evidence-2026-10-07-v1) is an evidence-only prerelease anchored to the typed-findings commit, not a customer or software release.
The [Git-tracked registry](../artifacts/keller-operator-evidence-2026-10-07.json) pins the catalog, archive parts, original nine-file historical bundle and archive-construction procedure by whole-file SHA-256 and byte length.
Use existing GitHub authentication with read access to this private repository; never put a token or connection string in an argument, file or graph record.

Run these commands from the repository root, replacing the private destination if needed:

```bash
umask 077
archive_dir="$HOME/keller-private/evidence-2026-10-07-v1"
mkdir -p "$archive_dir"
gh release download keller-operator-evidence-2026-10-07-v1 \
  --repo OpulentiaAI/keller-quotes --dir "$archive_dir"
catalog_sha=$(python3 -c 'import json; print(json.load(open("artifacts/keller-operator-evidence-2026-10-07.json"))["catalog"]["sha256"])')
python3 scripts/restore-keller-evidence.py \
  --catalog "$archive_dir/keller-operator-evidence-catalog.private.json" \
  --catalog-sha256 "$catalog_sha" \
  --out "$HOME/keller-private/restored-evidence-2026-10-07-v1"
```

The restore command authenticates the catalog against the Git pin, checks every part and content blob, and recreates byte-identical files in a new owner-private directory outside Git.
It refuses existing destinations, unsafe paths, symlinks, missing/extra/conflicting content and modified bytes; it does not execute archived programs or replay external effects.
The original nine-file `keller-historical-full-evidence-v1.private.zip` is also directly downloadable for the bounded 250-case classification audit.

## Coverage and boundaries

The catalog inventories retained operator files, original PDFs and transcripts, frozen inputs, private reports, original-byte receipts, all 441 input pins of the historical full-data seal, and verification evidence.
Content-identical files are stored once and retain their individual recovery paths.
The catalog keeps an explicit exclusion inventory for credentials, authentication/browser state, caches, disposable database/runtime files, Git checkouts and unclassified payloads; those are not business-evidence omissions relabeled as verified negatives.
The registry reports the actual archived path/blob/family counts and does not imply that unavailable original subagent files or unprovided Keller records were recovered.

Original private locator strings inside retained records are historical provenance, not portable source bindings.
After recovery, use approved local roots and the ignored source-binding file described in [[arsumbris-workspace]]; do not overwrite original sealed configurations or assume that extraction authenticates records or recreates a historical runtime.
New evidence, corrections or archival changes require a new version and Git registry update rather than overwriting this version.

Private targets, later acceptance and costs remain operator-only.
Never restore the archive into a quote-worker checkout, add it to a worker allowlist, expose it through a worker profile or use these archived outcomes as blinded-worker/judge context.
Restoration changes no production source, scheduler, knowledge activation, pricing rule or customer-release permission.

Git hashes and authenticated downloads establish bytes and access, not original authorship, independent review, trustworthy closure/ledger completeness or live quoting accuracy.
