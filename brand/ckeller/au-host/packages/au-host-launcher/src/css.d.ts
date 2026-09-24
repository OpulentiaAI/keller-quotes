// Side-effect CSS imports (`import './X.css'`) — the bundler injects the stylesheet; TS only needs
// to know the specifier resolves. The launcher's design slice imports its component CSS this way.
declare module '*.css'

// Static brand assets — vite resolves these to emitted file URLs at build.
declare module '*.webp' { const src: string; export default src }
declare module '*.svg' { const src: string; export default src }
declare module '*.svg?inline' { const src: string; export default src }
declare module '*.png' { const src: string; export default src }
declare module '*.jpg' { const src: string; export default src }
