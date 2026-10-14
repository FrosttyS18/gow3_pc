import type { Page } from "../App"
import { Tooltip } from "./Tooltip"
import { useI18n } from "../i18n"

/** CONTRATO DO LAUNCHER — navegação (IDs IMUTÁVEIS, separados dos rótulos):
 *  display, graphics, performance, game, patches, mods, controls, advanced, log
 *  + Música (AÇÃO de mute, não rota). Patches e Mods são PÁGINAS INDEPENDENTES.
 *  Rótulos CURTOS por idioma — nunca usar chaves de gow3_lang que representam
 *  funcionalidades DIFERENTES (ex.: "Mods & patches" para as duas rotas,
 *  "Gamepad names" para Controles). */
const PAGE_LABELS: Record<Page, { pt: string; en: string }> = {
  display:     { pt: "Tela",       en: "Display" },
  graphics:    { pt: "Gráficos",   en: "Graphics" },
  performance: { pt: "Desempenho", en: "Performance" },
  game:        { pt: "Jogo",       en: "Game" },
  patches:     { pt: "Patches",    en: "Patches" },
  mods:        { pt: "Mods",       en: "Mods" },
  controls:    { pt: "Controles",  en: "Controls" },
  advanced:    { pt: "Avançado",   en: "Advanced" },
  log:         { pt: "Registro",   en: "Log" },
  home:        { pt: "",           en: "" },
}

const ORDER: Page[] = [
  "display", "graphics", "performance", "game",
  "patches", "mods", "controls", "advanced", "log",
]

export function NavMenu({ page, onNavigate, musicMuted, onToggleMusic }: {
  page: Page
  onNavigate: (p: Page) => void
  musicMuted: boolean
  onToggleMusic: () => void
}) {
  const { t, language } = useI18n()
  const musicLabel = t("Play") === "Jogar" ? "Música" : "Music"
  return (
    <nav className="nav" aria-label="Menu">
      {ORDER.map((id) => (
        <button
          key={id}
          className={page === id ? "active" : ""}
          onClick={() => onNavigate(page === id ? "home" : id)}
        >
          {PAGE_LABELS[id][language === "pt" ? "pt" : "en"]}
        </button>
      ))}
      <button
        type="button"
        className="music-toggle"
        aria-pressed={musicMuted ? "false" : "true"}
        aria-label={musicMuted ? `${musicLabel}: ${t("Play") === "Jogar" ? "desligada — clique para ativar" : "off — click to turn on"}` : `${musicLabel}: ${t("Play") === "Jogar" ? "ligada — clique para silenciar" : "on — click to mute"}`}
        onClick={onToggleMusic}
      >
        <svg className="music-icon" width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
          {musicMuted ? (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" />
          ) : (
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4z" />
          )}
        </svg>
        {musicLabel}
      </button>
      <span className="nav-music-tip" aria-hidden="true">
        <Tooltip text={musicMuted
          ? (language === "pt" ? "Música desligada — clique para ativar" : "Music off — click to turn on")
          : (language === "pt" ? "Música ligada — clique para silenciar" : "Music on — click to mute")}>
          <span className="tip-anchor" tabIndex={-1} />
        </Tooltip>
      </span>
    </nav>
  )
}
