export type PlayPhase = "idle" | "preparing" | "running" | "error"

/** Ícone do Figma: barra vertical + seta para a direita ("|→"), à direita do texto. */
const EnterIcon = () => (
  <svg width="19" height="18" viewBox="0 0 19 18" aria-hidden="true">
    <rect x="0" y="1" width="1.6" height="16" fill="currentColor" />
    <path d="M6 9h11M12.5 4.5 17 9l-4.5 4.5"
      stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

/** JOGAR com os cinco estados REAIS — visual fiel ao Figma: retângulo discreto,
 *  texto leve Title Case, seta |→; nada de pílula, borda vermelha ou caps. */
export function PlayButton({ phase, available, error, onPlay }: {
  phase: PlayPhase
  available: boolean
  error: string
  onPlay: () => void
}) {
  const disabled = !available || phase === "preparing" || phase === "running"
  const label =
    phase === "preparing" ? "Preparando"
    : phase === "running" ? "Em execução"
    : "Jogar"
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
        {phase === "running" && <span className="dot" aria-hidden="true" />}
        {label}
        {phase !== "running" && <EnterIcon />}
      </button>
      <div className="sub">{sub}</div>
    </div>
  )
}
