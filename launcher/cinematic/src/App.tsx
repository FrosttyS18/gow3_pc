import { useCallback, useEffect, useRef, useState } from "react"
import { bridge, BridgeState } from "./bridge"
import { PAGES } from "./components/pages"
import { NavMenu } from "./components/NavMenu"
import { PlayButton, PlayPhase } from "./components/PlayButton"
import { StatusBar } from "./components/StatusBar"
import { MusicPlayer } from "./components/MusicPlayer"
import { TitleBar } from "./components/TitleBar"

export type Page = "home" | (typeof PAGES)[number]["id"]

export default function App() {
  const [state, setState] = useState<BridgeState | null>(null)
  const [page, setPage] = useState<Page>("home")
  const [phase, setPhase] = useState<PlayPhase>("idle")
  const [playError, setPlayError] = useState("")
  const [bridgeError, setBridgeError] = useState("")
  const startedAt = useRef(0)

  const refresh = useCallback(() => {
    bridge.state().then(setState).catch((e) => setBridgeError(String(e.message ?? e)))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // Poll do processo: preparing -> running -> finished/error pelo CÓDIGO DE SAÍDA REAL
  // gravado pelo monitor (não por palavras no log). Falhas de polling repetidas
  // aparecem para o usuário em vez de morrerem no console.
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
          return  // monitor ainda escrevendo o pid
        } else {
          if (status.outcome === "error") {
            setPhase("error")
            setPlayError((status.last_line || "o jogo terminou com erro")
              + (status.exit_code !== null ? ` (código ${status.exit_code})` : "")
              + " — detalhes no Registro")
            window.dispatchEvent(new CustomEvent("gow3:restore-music"))
          } else {
            setPhase("idle")
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

  const onPlay = async () => {
    if (!state?.game.found || phase === "preparing" || phase === "running") return
    setPlayError("")
    setPhase("preparing")
    startedAt.current = Date.now()
    try {
      await bridge.play()  // spawn aceito (validações incluídas): só agora o fade
      window.dispatchEvent(new CustomEvent("gow3:fade-music"))
    } catch (e) {
      setPhase("error")
      setPlayError(String((e as Error).message ?? e))
    }
  }


  return (
    <div className="app">
      <div className="art">
        <img src="art/bg-launcher.png" alt="" draggable={false}
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none" }} />
      </div>
      <TitleBar />
      <div className="logo" title="Início" onClick={() => setPage("home")}>
        <img src="art/logo-gow-3.png" alt="God of War III"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none"
            const el = document.createElement("span")
            el.className = "fallback"
            el.textContent = "GOD OF WAR III"
            ;(e.target as HTMLImageElement).parentElement?.appendChild(el)
          }} />
      </div>
      <NavMenu page={page} onNavigate={setPage} />
      {state && (
        <>
          <StatusBar
            summary={state.game.summary}
            missing={state.game.missing_files}
            bridgeError={bridgeError}
          />
          <MusicPlayer state={state.music} />
          <PlayButton
            phase={phase}
            available={state.game.found}
            error={playError}
            onPlay={onPlay}
          />
        </>
      )}
      {(() => {
        const active = PAGES.find((p) => p.id === page)
        if (!active || !state) return null
        const Page = active.component
        return (
          <div className="page-host">
            <Page state={state} refresh={refresh} />
          </div>
        )
      })()}
    </div>
  )
}
