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
  const [updateNotice, setUpdateNotice] = useState("")
  const [musicMuted, setMusicMuted] = useState(true)
  const [language, setLanguageState] = useState("en")
  const startedAt = useRef(0)
  const hiddenForPlay = useRef(false)

  // Background cinematográfico em VÍDEO: um único <video> mudo em loop cobre a mesma
  // área da imagem original (que permanece POR BAIXO como fallback imediato — sem
  // flash preto: o vídeo só aparece quando pronto, com fade). Pausa quando o jogo
  // abre (preparando/executando) e retoma ao voltar; a navegação entre páginas não
  // o remonta (o elemento vive fora do page-host), então ele nunca reinicia à toa.
  const videoRef = useRef<HTMLVideoElement>(null)
  const [videoReady, setVideoReady] = useState(false)
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.muted = true // propriedade DOM (o atributo do React nem sempre aplica a tempo)
    if (phase === "preparing" || phase === "running") {
      video.pause()
    } else {
      void video.play().catch(() => { /* autoplay pode ser adiado até interação */ })
    }
  }, [phase, videoReady])

  const refresh = useCallback(() => {
    bridge.state().then((s) => {
      setState(s)
      setLanguageState(String(s.app.ui_language ?? "en"))
    }).catch((e) => setBridgeError(String(e.message ?? e)))
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    if (!state?.app.check_updates) return
    bridge.updateCheck().then((r) => {
      if (r.newer) setUpdateNotice('Versão ' + r.latest + ' disponível — ver Avançado')
    }).catch(() => {})
  }, [state?.app.check_updates]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (state) setMusicMuted(state.music.muted) }, [state?.music.muted]) // eslint-disable-line react-hooks/exhaustive-deps
  useAmbientMusic(state?.music, musicMuted, phase)

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

  // HOTFIX P0: o fim da sessão do jogo chega por EVENTO do Rust (Job Object de sessão
  // + porta de conclusão do kernel — cobre reinícios internos do port). Nenhum polling:
  // zero processos e zero consultas enquanto o jogo está aberto. A fase "running" é
  // apenas estado local (timer), sem tocar em processo algum.
  useEffect(() => {
    if (phase !== "preparing" && phase !== "running") return
    const timer = setTimeout(() => setPhase("running"), 6000)
    return () => clearTimeout(timer)
  }, [phase])

  useEffect(() => {
    let disposed = false
    const off = (window as unknown as {
      __TAURI__?: { event: { listen: (name: string, handler: (event: { payload: { pid: number; exit_code: number } }) => void) => Promise<() => void> } }
    }).__TAURI__?.event.listen("gow3://game-end", async (event) => {
      if (disposed) return
      const { exit_code: exitCode } = event.payload
      if (exitCode !== 0) {
        setPhase("error")
        const status = await bridge.playStatus().catch(() => null)
        setPlayError((status?.last_line || "the game ended with an error")
          + ` (code ${exitCode})`
          + " — see the Log")
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
    })
    return () => { disposed = true; void off?.then((unlisten) => unlisten()) }
  }, [refresh])

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
          <video ref={videoRef} src="art/videolauncher.mp4" loop playsInline preload="auto"
            aria-hidden="true" tabIndex={-1}
            className={videoReady ? "bg-video on" : "bg-video"}
            onCanPlay={() => setVideoReady(true)}
            onError={() => setVideoReady(false)} />
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
              updateNotice={updateNotice}
            />
            <PlayButton
              phase={phase}
              available={state.game.found}
              error={playError}
              onPlay={onPlay}
            />
          </>
        )}
        {active && state && (
          <div className="page-host">
            {(() => {
              const Page = active.component
              return <Page state={state} refresh={refresh} />
            })()}
          </div>
        )}
      </div>
    </I18nContext.Provider>
  )
}
