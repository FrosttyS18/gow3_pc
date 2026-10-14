import type { Page } from "../App"
import { Tooltip } from "./Tooltip"
import { useI18n } from "../i18n"

/** Menu vertical fiel ao Figma, com as páginas REAIS do launcher original e a
 *  décima opção MÚSICA — uma AÇÃO (mute/religar), não uma rota. Os rótulos vêm
 *  do i18n central (gow3_lang) — a troca de idioma é imediata. */
export function NavMenu({ page, onNavigate, musicMuted, onToggleMusic }: {
  page: Page
  onNavigate: (p: Page) => void
  musicMuted: boolean
  onToggleMusic: () => void
}) {
  const { t } = useI18n()
  const items: { id: Page; label: string }[] = [
    { id: "display", label: t("Display & FPS") },
    { id: "graphics", label: t("Graphics") },
    { id: "performance", label: t("Performance") },
    { id: "game", label: t("Game & effects") },
    { id: "patches", label: t("Mods & patches") },
    { id: "mods", label: t("Mods & patches") },
    { id: "controls", label: t("Gamepad names") },
    { id: "advanced", label: t("Advanced") },
    { id: "log", label: t("Log") },
  ]
  return (
    <nav className="nav" aria-label={t("Log")}>
      {items.map(({ id, label }) => (
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
        aria-label={musicMuted ? t("Play") + " música" : t("Stop") + " música"}
        onClick={onToggleMusic}
      >
        <svg className="music-icon" width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
          {musicMuted ? (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" />
          ) : (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z" />
          )}
        </svg>
        {t("Play") === "Jogar" ? "Música" : "Music"}
      </button>
      <span className="nav-music-tip" aria-hidden="true">
        <Tooltip text={musicMuted
          ? (t("Play") === "Jogar" ? "Música desligada — clique para ativar" : "Music off — click to turn on")
          : (t("Play") === "Jogar" ? "Música ligada — clique para silenciar" : "Music on — click to mute")}>
          <span className="tip-anchor" tabIndex={-1} />
        </Tooltip>
      </span>
    </nav>
  )
}
