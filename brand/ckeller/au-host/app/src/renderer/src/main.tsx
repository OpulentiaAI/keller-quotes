import './dev-flag' // MUST be first — sets the DEV split-bridge flag before container-core's eager init evals

import React from 'react'
import ReactDOM from 'react-dom/client'

import { installDiagnosticConditionBridge } from '@arsumbris/au-host-sdk'

import { App } from './App'
import { applyStoredTheme } from './projections/theme-store'
import { installDomBoundsDetector } from './projections/dom-bounds-detector'
import { installComponentOverlayChannel } from './projections/overlay-site'
import { installEventReadBridge } from './projections/event-read-bridge'
// The FOUNDATION typeface (@font-face for Geist), so the `--au-font-*` the tokens name actually load.
// It lives in @arsumbris/style alongside the shared tokens,
// shared by every consumer incl. the shadow-DOM custom elements (@font-face is document-global).
import '@arsumbris/style/fonts.css'
// First-party design tokens, injected at the renderer root so every mounted
// projection inherits the --au-* tokens via the shared-DOM cascade.
import '@arsumbris/style/tokens.css'
// The extension layer, loaded AFTER the base so its :root derivations win: it adds the type /
// ink / code / z-index scales and re-points the base colour aliases at the warm ladders.
import '@arsumbris/style/ext.css'
import './app.css'

// Route host diagnostics into the event substrate's condition set (surfaced in the trace inspector),
// keeping the console floor. Once, at boot, before anything reports.
installDiagnosticConditionBridge()

// Publish this window's overlay `claim` to the component-overlay channel, so a `<au-*>` component can
// reach `host.overlay`. Once, at boot, before any component upgrades. See `installComponentOverlayChannel`.
installComponentOverlayChannel()

// Expose the READ-ONLY event views on `window.__auEvents` when the substrate is enabled (E2E / debugging).
// Gated by the same `?au-events=` toggle, so a plain prod renderer exposes nothing.
installEventReadBridge()

// Apply the active theme BEFORE first paint — the launcher phase mounts without ProjectionHost,
// so without this it renders on bare token defaults and the shipped theme only appears after boot.
applyStoredTheme()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

// Drop the static boot splash once React has painted its first frame (two rAFs = after the initial
// commit is on screen), so the app content is already visible underneath when the splash lifts —
// no black flash between the two. See the splash in index.html.
requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById('boot-splash')?.remove()))

// DEV-only tripwire: report any node appended straight to `document.body`, outside the composition
// root and the host overlay site. The gate lives HERE so the detector module stays env-agnostic and
// testable; it never runs in a production renderer.
if (import.meta.env.DEV) installDomBoundsDetector()
