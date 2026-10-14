import { useEffect, useRef, useState } from "react"
import { bridge, MusicState } from "../bridge"

/** Música ambiente (canto superior esquerdo, discreto): apenas mudo + volume.
 *  A faixa é o MP3 local do mantenedor; autoplay começa na primeira interação
 *  (limitação do WebView2), volume e mudo persistem em settings.json e o
 *  fade-out de 2s ao JOGAR não bloqueia a inicialização. */
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
      if (element.src && element.paused) {
        element.play().catch(() => {})
      }
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
      audio.current.play().catch(() => {})  // se bloqueado, a primeira interação inicia
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
      <button onClick={toggleMute} aria-label={muted ? "Ativar som" : "Silenciar"}>
        {muted || volume === 0
          ? <svg width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" /></svg>
          : <svg width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a6.8 6.8 0 0 1 0 13.4v2.1a8.8 8.8 0 0 0 0-17.6z" /></svg>}
      </button>
      <input type="range" min={0} max={1} step={0.01} value={volume}
        onChange={(e) => changeVolume(Number(e.target.value))}
        aria-label="Volume da música ambiente" />
    </div>
  )
}
