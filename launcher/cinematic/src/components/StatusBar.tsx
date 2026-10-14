/** Bottom-left indicators: the port's own summary line (Native (1080p) · N FPS engine ·
 *  N patches) over a thin blood rule — exactly the Figma footer. */
export function StatusBar({ summary, missing, bridgeError, updateNotice }: {
  summary: string
  missing: string[]
  bridgeError: string
  updateNotice?: string
}) {
  return (
    <footer className="statusbar">
      <div className="line">
        {updateNotice && !bridgeError
          ? <span className="dim">{updateNotice}</span>
        : bridgeError
          ? <span className="dim">ponte Python indisponível — {bridgeError}</span>
          : <>
              {summary}
              {missing.length > 0 && (
                <span className="dim"> · dump incompleto: {missing.slice(0, 3).join(", ")}</span>
              )}
            </>}
      </div>
      <div className="rule" aria-hidden="true" />
    </footer>
  )
}
