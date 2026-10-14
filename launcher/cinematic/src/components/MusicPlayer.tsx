import { useEffect, useRef, useState } from "react"
import { bridge, MusicState } from "../bridge"

/* Controle de música (canto superior esquerdo, faixa própria acima do painel de
 * vidro). Estado INICIAL RECOLHIDO: alto-falante branco + "Música" leve sobre
 * superfície preta com borda vermelha; o slider aparece só ao interagir.
 *
 * P0 (travamento): o volume responde IMEDIATAMENTE em memória (elemento de
 * áudio) e a persistência é DEBOUNCED (500 ms após a última interação) — nunca
 * um processo de ponte por movimento do mouse; falhas de gravação aparecem no
 * controle em vez de só no console, e o valor anterior é preservado. */
export function MusicPlayer({ state }: { state: MusicState; onChange?: () => void }) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [audioOk, setAudioOk] = useState(true)
  const [volume, setVolume] = useState(state.volume)
  const [muted, setMuted] = useState(state.muted)
  const [notice, setNotice] = useState("")
  const [available, setAvailable] = useState(false)
  const saveTimer = useRef<number | undefined>(undefined)
  const volumeRef = useRef(volume)
  const mutedRef = useRef(muted)

  useEffect(() => {
    audio.current = new Audio()
    audio.current.loop = true
    const element = audio.current
    const fade = () => {
      const start = element.volume
      const beganAt = performance.now()
      const step = () => {
        const t = Math.min(1, (performance.now() - beganAt) / 2000)
        element.volume = start * (1 - t)
        if (t < 1) requestAnimationFrame(step)
        else element.pause()
      }
      step()
    }
    window.addEventListener("gow3:fade-music", fade)
    window.addEventListener("gow3:restore-music", () => { element.volume = mutedRef.current ? 0 : volumeRef.current })
    const kick = () => {  // WebView2 autoplay: a primeira interação libera o áudio
      if (element.src && element.paused) {
        element.play().then(() => setAvailable(true)).catch(() => setAvailable(false))
      }
    }
    window.addEventListener("pointerdown", kick)
    return () => {
      window.removeEventListener("gow3:fade-music", fade)
      window.removeEventListener("pointerdown", kick)
      element.pause()
    }
  }, [])

  useEffect(() => {
    const path = state.file || state.default_path
    if (!path) return
    bridge.musicDataUrl(path).then((url) => {
      if (!url || !audio.current) {
        setAudioOk(false)
        return
      }
      audio.current.src = url
      audio.current.volume = muted ? 0 : volume
      audio.current.play()
        .then(() => { setAvailable(true); setAudioOk(true) })
        .catch(() => setAvailable(false))  // autoplay bloqueado: inicia na 1ª interação
    }).catch(() => setAudioOk(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.file, state.default_path])

  /** Persistência debounced: uma única gravação após o usuário parar de mover. */
  const persist = (values: Record<string, string | number | boolean>) => {
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      bridge.setApp(values).then(() => setNotice("")).catch((e) => {
        setNotice("Não foi possível salvar: " + String((e as Error).message ?? e).slice(0, 80))
        window.setTimeout(() => setNotice(""), 4000)
      })
    }, 500)
  }

  const changeVolume = (value: number) => {
    setVolume(value)
    volumeRef.current = value
    if (audio.current && !muted) audio.current.volume = value
    persist({ ambient_volume: value })
  }

  const toggleMute = () => {
    const next = !muted
    setMuted(next)
    mutedRef.current = next
    if (audio.current) audio.current.volume = next ? 0 : volume
    persist({ ambient_muted: next })
  }

  return (
    <div className={"music" + (!available || !audioOk ? " unavailable" : "")}>
      <button type="button" className="music-main" onClick={toggleMute}
        aria-label={muted ? "Ativar música" : "Silenciar música"}
        aria-pressed={muted} title={audioOk ? undefined : "Faixa de música não encontrada"}>
        {muted || volume === 0 ? (
          <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" />
          </svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a6.8 6.8 0 0 1 0 13.4v2.1a8.8 8.8 0 0 0 0-17.6z" />
          </svg>
        )}
        <span className="music-label">Música</span>
      </button>
      <div className="music-volume" aria-label="Volume da música ambiente">
        <input type="range" min={0} max={1} step={0.01} value={volume}
          onChange={(e) => changeVolume(Number(e.target.value))}
          aria-label="Volume da música ambiente" />
      </div>
      {notice && <span className="music-notice" role="alert">{notice}</span>}
    </div>
  )
}
