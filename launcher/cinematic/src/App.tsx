import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { bridge, BridgeState } from "./bridge"
import { I18nContext, LangTable, translate } from "./i18n"
import { PAGES } from "./components/pages"
import { NavMenu } from "./components/NavMenu"
import { PlayButton, PlayPhase } from "./components/PlayButton"
import { StatusBar } from "./components/StatusBar"
import { useAmbientMusic } from "./components/useAmbientMusic"
import { TitleBar } from "./components/TitleBar"

export type Page = "home" | (typeof PAGES)[number]["id"]

export default function App() {
  const [state, setState] = useState<BridgeState | null>(null)
  const [page, setPage] = useState<Page>("home")
  const [phase, setPhase] = useState<PlayPhase>("idle")
  const [playError, setPlayError] = useState("")
  const [bridgeError, setBridgeError] = useState("")
  const [musicMuted, setMusicMuted] = useState(true)
  const [language, setLanguageState] = useState("en")
  const startedAt = useRef(0)
  const hiddenForPlay = useRef(false)

  const refresh = useCallback(() => {
    bridge.state().then((s) => {
      setState(s)
      setLanguageState(String(s.app.ui_language ?? "en"))
    }).catch((e) => setBridgeError(String(e.message ?? e)))
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { if (state) setMusicMuted(state.music.muted) }, [state?.music.muted]) // eslint-disable-line react-hooks/exhaustive-deps
  useAmbientMusic(state?.music, musicMuted, phase)

  // i18n: troca IMEDIATA (sem reiniciar); a ponte grava só quando o usuário muda
  const setLanguage = useCallback((next: string) => {
    setLanguageState(next)
    bridge.setApp({ ui_language: next }).catch((e) => console.error("ui_language", e))
  }, [])
  const i18n = useMemo(() => {
    const table: LangTable = state?.translations?.[language] ?? {}
    return {
      language,
      setLanguage,
      t: (english: string, ...args: (string | number)[]) => translate(table, english, ...args),
      tables: state?.translations ?? {},
    }
  }, [language, state?.translations, setLanguage])

  // Poll do processo pelo CÓDIGO DE SAÍDA REAL
  useEffect(() => {
    if (phase !== "preparing" && phase !== "running") return
    let failures = 0
    const timer = setInterval(async () => {
      try {
        const status = await bridge.playStatus()
        failures = 0
        setBridgeError("")
        if (status.running) {
          setPhase(Date.now() - startedAt.current > 6000 ? "running" : "preparing")
        } else if (status.outcome === "unknown" && Date.now() - startedAt.current < 8000) {
          return
        } else {
          if (status.outcome === "error") {
            setPhase("error")
            setPlayError((status.last_line || "o jogo terminou com erro")
              + (status.exit_code !== null ? ` (código ${status.exit_code})` : "")
              + " — detalhes no Registro")
            window.dispatchEvent(new CustomEvent("gow3:restore-music"))
          } else {
            setPhase("idle")
            if (hiddenForPlay.current) {
              hiddenForPlay.current = false
              window.dispatchEvent(new CustomEvent("gow3:restore-music"))
              await (window as unknown as { __TAURI__?: { window: { getCurrentWindow: () => { close(): Promise<void> } } } })
                .__TAURI__?.window.getCurrentWindow().close()
              return
            }
          }
          refresh()
        }
      } catch (e) {
        failures += 1
        if (failures >= 3) {
          setBridgeError("Falha ao acompanhar o jogo: " + String((e as Error).message ?? e))
        }
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [phase, refresh])

  // Música é uma AÇÃO do menu
  const toggleMusic = () => {
    const next = !musicMuted
    setMusicMuted(next)
    bridge.setApp({ ambient_muted: next }).catch((e) => console.error("ambient_muted", e))
  }

  const onPlay = async () => {
    if (!state?.game.found || phase === "preparing" || phase === "running") return
    setPlayError("")
    setPhase("preparing")
    startedAt.current = Date.now()
    // P0 M1.7: a música PARA ANTES de qualquer operação da ponte — determinístico
    window.dispatchEvent(new CustomEvent("gow3:stop-music"))
    try {
      await bridge.play()
      window.dispatchEvent(new CustomEvent("gow3:fade-music"))
      if (state?.app.close_on_play) {
        await (window as unknown as { __TAURI__?: { window: { getCurrentWindow: () => { hide(): Promise<void> } } } })
          .__TAURI__?.window.getCurrentWindow().hide()
        hiddenForPlay.current = true
      }
    } catch (e) {
      setPhase("error")
      setPlayError(String((e as Error).message ?? e))
    }
  }

  const active = PAGES.find((p) => p.id === page)

  return (
    <I18nContext.Provider value={i18n}>
      <div className="app">
        <div className="art">
          <img src="art/bg-launcher.png" alt="" draggable={false}
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none" }} />
        </div>
        <TitleBar />
        <div className="logo" aria-label={i18n.t("Play")} role="button" tabIndex={0}
          onClick={() => setPage("home")}
          onKeyDown={(e) => { if (e.key === "Enter") setPage("home") }}>
          <img src="art/logo-gow-3.png" alt="God of War III"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none"
              const el = document.createElement("span")
              el.className = "fallback"
              el.textContent = "GOD OF WAR III"
              ;(e.target as HTMLImageElement).parentElement?.appendChild(el)
            }} />
        </div>
        <NavMenu page={page} onNavigate={setPage} musicMuted={musicMuted} onToggleMusic={toggleMusic} />
        {state && (
          <>
            <StatusBar
              summary={state.game.summary}
              missing={state.game.missing_files}
              bridgeError={bridgeError}
            />
            <PlayButton
              phase={phase}
              available={state.game.found}
              error={playError}
              onPlay={onPlay}
            />
          </>
        )}
        {active && state && <div className="page-host">{active.component({ state, refresh })}</div>}
      </div>
    </I18nContext.Provider>
  )
}
