import type { Page } from "../App"

/** Menu vertical fiel ao Figma, com as páginas REAIS do launcher original e a
 *  décima opção MÚSICA — uma AÇÃO (mute/religar), não uma rota: não muda a
 *  página selecionada, não abre painel e NUNCA recebe a linha vermelha de
 *  seleção. Mesma tipografia/hover dos demais itens; ícone discreto de alto-
 *  falante refletindo o estado (aria-pressed). */
const ITEMS: { id: Page; label: string }[] = [
  { id: "display", label: "Display" },
  { id: "graphics", label: "Gráficos" },
  { id: "performance", label: "Performance" },
  { id: "game", label: "Game" },
  { id: "patches", label: "Patches" },
  { id: "mods", label: "Mods" },
  { id: "controls", label: "Controls" },
  { id: "advanced", label: "Advanced" },
  { id: "log", label: "Log" },
]

export function NavMenu({ page, onNavigate, musicMuted, onToggleMusic }: {
  page: Page
  onNavigate: (p: Page) => void
  musicMuted: boolean
  onToggleMusic: () => void
}) {
  return (
    <nav className="nav" aria-label="Menu principal">
      {ITEMS.map(({ id, label }) => (
        <button
          key={id}
          className={page === id ? "active" : ""}
          onClick={() => onNavigate(page === id ? "home" : id)}
        >
          {label}
        </button>
      ))}
      <button
        type="button"
        className="music-toggle"
        aria-pressed={musicMuted ? "false" : "true"}
        aria-label={musicMuted ? "Ativar música" : "Silenciar música"}
        title={musicMuted ? "Música desligada — clique para ligar" : "Música ligada — clique para silenciar"}
        onClick={onToggleMusic}
      >
        <svg className="music-icon" width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
          {musicMuted ? (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" />
          ) : (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z" />
          )}
        </svg>
        Música
      </button>
    </nav>
  )
}
