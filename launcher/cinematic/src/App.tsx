import { useCallback, useEffect, useRef, useState } from "react"
import { bridge, BridgeState } from "./bridge"
import { NavMenu } from "./components/NavMenu"
import { PlayButton, PlayPhase } from "./components/PlayButton"
import { StatusBar } from "./components/StatusBar"
import { DisplayPage } from "./components/DisplayPage"
import { MusicPlayer } from "./components/MusicPlayer"
import { TitleBar } from "./components/TitleBar"

export type Page = "home" | "display" | "performance" | "game" | "patches"
  | "mods" | "controls" | "advanced" | "log"

export default function App() {
  const [state, setState] = useState<BridgeState | null>(null)
  const [page, setPage] = useState<Page>("home")
  const [phase, setPhase] = useState<PlayPhase>("idle")
  const [playError, setPlayError] = useState("")
  const [bridgeError, setBridgeError] = useState("")
  const startedAt = useRef(0)

  const refresh = useCallback(() => {
    bridge.state().then(setState).catch((e) => {
      setBridgeError(String(e.message ?? e))
      document.title = `ERR ${String(e.message ?? e).slice(0, 80)}`
    })
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // poll the started run.py: preparing (first instants) -> running -> finished/error
  useEffect(() => {
    if (phase !== "preparing" && phase !== "running") return
    const timer = setInterval(async () => {
      try {
        const status = await bridge.playStatus()
        if (status.running) {
          setPhase(Date.now() - startedAt.current > 6000 ? "running" : "preparing")
        } else if (phase === "running" || Date.now() - startedAt.current > 6000) {
          setPhase(status.outcome === "error" ? "error" : "idle")
          if (status.outcome === "error") setPlayError("run.py terminou com erro — ver Log")
          refresh()
        }
      } catch { /* bridge hiccup: keep polling */ }
    }, 1500)
    return () => clearInterval(timer)
  }, [phase, refresh])

  const onPlay = async () => {
    if (!state?.game.found || phase === "preparing" || phase === "running") return
    setPlayError("")
    setPhase("preparing")
    startedAt.current = Date.now()
    window.dispatchEvent(new CustomEvent("gow3:fade-music"))
    try {
      await bridge.play()
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
      {(state || bridgeError) && (
        <>
          <StatusBar
            summary={state?.game.summary ?? ""}
            missing={state?.game.missing_files ?? []}
            bridgeError={bridgeError}
          />
          {state && (
            <>
              <MusicPlayer state={state.music} onChange={refresh} />
              <PlayButton
                phase={phase}
                available={state.game.found}
                error={playError}
                onPlay={onPlay}
              />
            </>
          )}
        </>
      )}
      {page === "display" && state && (
        <DisplayPage ini={state.ini} choices={state.choices} onChanged={refresh} />
      )}
    </div>
  )
}
