import { useEffect, useRef, useState } from "react"
import { bridge, MusicState } from "../bridge"

/* Controle de música (canto superior esquerdo) — referência do mantenedor:
 * estado INICIAL RECOLHIDO: ícone de alto-falante branco + texto "Música"
 * leve sobre superfície preta com borda vermelha arredondada. O slider de
 * volume SÓ aparece ao interagir (hover/foco), com fechamento previsível.
 * Apenas mudo/reativação e volume — nenhum outro controle. */
export function MusicPlayer({ state, onChange }: { state: MusicState; onChange: () => void }) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [volume, setVolume] = useState(state.volume)
  const [muted, setMuted] = useState(state.muted)

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
    const kick = () => {  // WebView2 autoplay: a primeira interação libera o áudio
      if (element.src && element.paused) element.play().catch(() => {})
      window.removeEventListener("pointerdown", kick)
    }
    window.addEventListener("gow3:fade-music", fade)
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
      if (!url || !audio.current) return
      setSrc(url)
      audio.current.src = url
      audio.current.volume = muted ? 0 : volume
      audio.current.play().catch(() => {})
    }).catch(() => setSrc(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.file, state.default_path])

  const persist = (values: Record<string, string | number | boolean>) => {
    bridge.setApp(values).then(onChange).catch((e) => console.error("set_app", e))
  }

  const changeVolume = (value: number) => {
    setVolume(value)
    if (audio.current && !muted) audio.current.volume = value
    persist({ ambient_volume: value })
  }

  const toggleMute = () => {
    const next = !muted
    setMuted(next)
    if (audio.current) audio.current.volume = next ? 0 : volume
    persist({ ambient_muted: next })
  }

  return (
    <div className="music" data-has-audio={src ? "yes" : "no"}>
      <button type="button" className="music-main" onClick={toggleMute}
        aria-label={muted ? "Ativar música" : "Silenciar música"}
        aria-pressed={muted}>
        {muted || volume === 0 ? (
          <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" />
          </svg>
        ) : (
          <svg width="17" height="17" viewBox="0 0 24 24" aria-hidden="true">
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
    </div>
  )
}
