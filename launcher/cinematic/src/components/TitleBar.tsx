/** Frameless window chrome: a drag region plus minimal close/minimize glyphs.
 *  Uses the Tauri window API when present (capability-gated); inert in the browser. */
export function TitleBar() {
  const api = (window as unknown as {
    __TAURI__?: { window: { getCurrentWindow: () => { minimize: () => void; close: () => void } } }
  }).__TAURI__
  return (
    <div className="titlebar" data-tauri-drag-region>
      <button className="glyph" aria-label="Minimizar" disabled={!api}
        onClick={() => api?.window.getCurrentWindow().minimize()}>—</button>
      <button className="glyph close" aria-label="Fechar" disabled={!api}
        onClick={() => api?.window.getCurrentWindow().close()}>✕</button>
    </div>
  )
}
