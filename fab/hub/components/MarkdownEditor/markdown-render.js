// === markdown-render: shared markdown-it renderer factory (katex, no raw html) ===
// Used by thoughtgraph nodes (via MarkdownEditor, which adds wikilinks) and the
// INT3RF4CE chat. Depends on the global `markdownit`, `markdownItKatex`, `katex`.
function makeMarkdownRenderer() {
  // cybersec: html: false makes markdown-it escape raw HTML — without it a
  // <script> or <img onerror> in model output or notes would run in the page
  return window.markdownit({ html: false, linkify: true, typographer: false })
    .use(window.markdownItKatex, { throwOnError: false });
}
