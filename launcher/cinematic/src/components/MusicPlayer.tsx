import { useEffect, useRef, useState } from "react"
import { bridge, MusicState } from "../bridge"

/** Ambient music: the maintainer's local MP3 (default art/ambient.mp3 or a picked
 *  file), persistent volume, mute, play/pause and a 2s non-blocking fade-out when
 *  JOGAR starts the game. The UI stays discreet: a single glyph that expands only
 *  on hover/focus, never competing with the JOGAR button. Nothing is bundled. */
export function MusicPlayer({ state, onChange }: { state: MusicState; onChange: () => void }) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [src, setSrc] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
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
    window.addEventListener("gow3:fade-music", fade)
    return () => { window.removeEventListener("gow3:fade-music", fade); element.pause() }
  }, [])

  useEffect(() => {
    const path = state.file || state.default_path
    if (!path) return
    bridge.musicDataUrl(path).then((url) => {
      if (!url) return
      setSrc(url)
      const element = audio.current
      if (!element) return
      element.src = url
      element.volume = muted ? 0 : volume
      element.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
    }).catch(() => setSrc(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.file, state.default_path])

  const persist = (values: Record<string, string | number | boolean>) => {
    bridge.setApp(values).then(onChange).catch((e) => console.error("set_app", e))
  }

  const toggle = () => {
    const element = audio.current
    if (!element || !src) return
    if (playing) { element.pause(); setPlaying(false) }
    else {
      element.volume = muted ? 0 : volume
      element.play().then(() => setPlaying(true)).catch(() => {})
    }
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

  const pick = async () => {
    const path = await bridge.pickMusic()
    if (!path) return
    persist({ ambient_file: path })
    onChange()
  }

  return (
    <div className="music" title={src ? "" : "Escolha um MP3 local"}>
      <button onClick={toggleMute} aria-label={muted ? "Ativar som" : "Silenciar"}>
        {muted || volume === 0
          ? <svg width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3 3.5 3.5-1.4 1.4L15 13.4 11.5 17l-1.4-1.4L13.6 12l-3.5-3.6L11.5 7l3.5 3.6L18.6 7 20 8.4 16.5 12z" /></svg>
          : <svg width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a6.8 6.8 0 0 1 0 13.4v2.1a8.8 8.8 0 0 0 0-17.6z" /></svg>}
      </button>
      <span className="expand">
        <input type="range" min={0} max={1} step={0.01} value={volume}
          onChange={(e) => changeVolume(Number(e.target.value))}
          aria-label="Volume da música ambiente" />
        <button onClick={toggle} aria-label={playing ? "Pausar música" : "Tocar música"}>
          {playing
            ? <svg width="14" height="14" viewBox="0 0 24 24"><path fill="currentColor" d="M6 5h4v14H6zM14 5h4v14h-4z" /></svg>
            : <svg width="14" height="14" viewBox="0 0 24 24"><path fill="currentColor" d="M7 4v16l13-8z" /></svg>}
        </button>
        <button onClick={pick} aria-label="Escolher arquivo de música">
          <svg width="14" height="14" viewBox="0 0 24 24"><path fill="currentColor" d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z" /></svg>
        </button>
      </span>
    </div>
  )
}
