# Opulent × C. Keller — Ars Umbris brand overlay

CKeller branding for the Ars Umbris build (`au-host`), pulled from ckellermfg.com
via the Context.dev MCP (`get-brand`, `brand-retrieve-unified`, `web-fonts`,
`web-scrape-images`) and applied as an in-repo overlay.

## What's here

`au-host/` mirrors the au-host repository layout — each file lands at the same
path inside an `arsumbris/au-host` checkout. Baseline: `au-host @ 0e85fb1`
(release 0.0.1-alpha). New files are safe anywhere; the modified files below are
full replacements, so diff before overwriting if au-host has moved on.

### Brand inputs (contextdev)

- Colors: `#0568dd` (C. Keller blue), `#609eea` (light blue), `#05386b` (deep
  blue), navies `#07101d` / `#051d31`, steels `#6b6c6e` / `#9b9b9c`
- Faces: **Inter** (UI) + **JetBrains Mono** (mono accents) — both SIL OFL,
  vendored as variable woff2
- Mark: navy rounded-square "CK" monogram (blue stroke + letterforms)
- Slogan: **"Manufacturing Ready to Deliver."**
- Product shots (ckellermfg.com `/images/*.webp`): laser cutting, welding,
  metal forming, prototyping, high/low-volume runs, assembly, finishing,
  engineering support, CNC, the Villa Park delivery truck, USA badge, footer
  wordmark

### Files

| Path (inside au-host) | Change |
|---|---|
| `packages/style/themes/ckeller.theme.css` | NEW — CKeller palette as a `:root` theme instance (navy surfaces, `#0568dd` accent/CTA) in the umbris token pattern |
| `packages/style/themes/ckeller.theme.yaml` | NEW — theme manifest (`name: CKeller`) |
| `packages/style/default-theme.ts` | MOD — ships `CKeller — Flat` as the default theme |
| `packages/style/fonts.css` | MOD — `@font-face` Inter + JetBrains Mono (was Geist) |
| `packages/style/ext.css` | MOD — `--au-font-sans`/`--au-font-mono` stacks point at the new faces |
| `packages/style/assets/fonts/Inter-Variable.woff2` | NEW — OFL variable face |
| `packages/style/assets/fonts/JetBrainsMono-Variable.woff2` | NEW — OFL variable face |
| `packages/au-host-launcher/src/Welcome.tsx` | MOD — "Opulent × C. Keller" lockup (CK mark + slogan) and 4-shot capability strip on the start-here |
| `packages/au-host-launcher/src/welcome.css` | MOD — lockup + filmstrip styles |
| `packages/au-host-launcher/src/css.d.ts` | MOD — `*.webp`/`*.svg`/`*.png`/`*.jpg` module declarations for asset imports |
| `packages/au-host-launcher/src/assets/` | NEW — `ckeller-mark.svg` + `ck-*.webp` product shots |
| `app/src/renderer/src/main.tsx` | MOD — `applyStoredTheme()` before first paint; the launcher phase mounts before ProjectionHost and previously rendered on bare token defaults |

## Apply

```sh
# from a clean arsumbris/au-host checkout at commit 0e85fb1
cp -R brand/ckeller/au-host/. /path/to/arsumbris/au-host/
pnpm -C /path/to/arsumbris/au-host install   # if needed
pnpm -C /path/to/arsumbris/au-host/app build
```

Then run `pnpm dev` in `app/` — the start-here renders the Opulent × C. Keller
lockup over the navy theme with the blue CTA. Any device that already picked a
theme keeps its stored choice (per-machine precedence); clear
`localStorage['au-host.theme.preferences']` to see the new default.
