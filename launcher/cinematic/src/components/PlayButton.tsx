export type PlayPhase = "idle" | "preparing" | "running" | "error"

const PlayIcon = () => (
  <svg width="17" height="20" viewBox="0 0 17 20" aria-hidden="true">
    <path d="M1 1.6v16.8c0 .9 1 1.5 1.8 1L16 11.2c.8-.5.8-1.8 0-2.3L2.8.6C2 .1 1 .7 1 1.6z"
      fill="currentColor" />
  </svg>
)

/** JOGAR with the five REAL states — never decorative: unavailable comes from the
 *  game detection, preparing/running from the live run.py process, error from it. */
export function PlayButton({ phase, available, error, onPlay }: {
  phase: PlayPhase
  available: boolean
  error: string
  onPlay: () => void
}) {
  const disabled = !available || phase === "preparing" || phase === "running"
  const label =
    phase === "preparing" ? "PREPARANDO"
    : phase === "running" ? "EM EXECUÇÃO"
    : !available ? "JOGAR"
    : "JOGAR"
  const sub =
    phase === "error" ? (error || "Erro ao iniciar — ver Log")
    : !available ? "pasta do jogo não configurada"
    : phase === "preparing" ? "preparando o jogo…"
    : phase === "running" ? "executando"
    : ""
  return (
    <div className={phase === "error" ? "play err" : "play"}>
      <button className="btn" disabled={disabled} onClick={onPlay}
        aria-label="Jogar God of War III">
        {phase === "running"
          ? <span className="dot" aria-hidden="true" />
          : <PlayIcon />}
        {label}
      </button>
      <div className="sub">{sub}</div>
    </div>
  )
}
