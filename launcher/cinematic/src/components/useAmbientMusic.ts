import { useEffect, useRef } from "react"
import { bridge, MusicState } from "../bridge"

/** Música ambiente do launcher cinematográfico — decisão definitiva do mantenedor
 *  (M1.5): volume FIXO em 5% (0,05); a única preferência persistida é o mute
 *  (ambient_muted em settings.json, uma gravação por clique, sem tempestade de
 *  pontes). Faixa: MP3 local do mantenedor; autoplay do WebView2 contornado na
 *  primeira interação; UMA instância de áudio; fade-out ao iniciar o jogo e
 *  restauração em falha — com token de geração que CANCELA fades pendentes
 *  (um fade antigo nunca silencia a música após um restore). */
export const MUSIC_FIXED_VOLUME = 0.03

export function useAmbientMusic(music: MusicState | undefined, muted: boolean) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const mutedRef = useRef(muted)
  const fadeToken = useRef(0)
  mutedRef.current = muted

  useEffect(() => {
    const element = new Audio()
    element.loop = true
    audio.current = element
    ;(window as unknown as { __gow3Audio?: HTMLAudioElement }).__gow3Audio = element

    const applyVolume = () => { element.volume = mutedRef.current ? 0 : MUSIC_FIXED_VOLUME }

    const fadeOut = () => {
      const token = ++fadeToken.current
      const start = element.volume
      const beganAt = performance.now()
      const step = () => {
        if (token !== fadeToken.current) return  // cancelado por restore/religamento
        const t = Math.min(1, (performance.now() - beganAt) / 2000)
        element.volume = start * (1 - t)
        if (t < 1) requestAnimationFrame(step)
        else element.pause()
      }
      step()
    }
    const restore = () => {
      fadeToken.current++                       // cancela qualquer fade em andamento
      applyVolume()
      // blindagem: reafirma o volume INCONDICIONALMENTE por alguns frames — 0 é
      // ambíguo (mute vs fade zerado) e nenhum step residual pode sobreviver
      for (let frame = 1; frame <= 4; frame++) {
        requestAnimationFrame(() => applyVolume())
      }
      if (element.src) element.play().catch(() => {})  // autoplay pode exigir gesto
    }
    const kick = () => {                         // WebView2: primeira interação libera
      if (element.src && element.paused && !mutedRef.current) {
        applyVolume()
        element.play().catch(() => {})
      }
    }
    window.addEventListener("gow3:fade-music", fadeOut)
    window.addEventListener("gow3:restore-music", restore)
    window.addEventListener("pointerdown", kick)
    return () => {
      window.removeEventListener("gow3:fade-music", fadeOut)
      window.removeEventListener("gow3:restore-music", restore)
      window.removeEventListener("pointerdown", kick)
      fadeToken.current++
      element.pause()
      audio.current = null
    }
  }, [])

  // mute/religamento: volume fixo, sem tocar na faixa
  useEffect(() => { if (audio.current) audio.current.volume = muted ? 0 : MUSIC_FIXED_VOLUME }, [muted])

  // carrega a faixa UMA vez por caminho
  useEffect(() => {
    if (!music) return
    const path = music.file || music.default_path
    if (!path || !audio.current) return
    bridge.musicDataUrl(path).then((url) => {
      if (!url || !audio.current) return
      audio.current.src = url
      audio.current.volume = mutedRef.current ? 0 : MUSIC_FIXED_VOLUME
      audio.current.play().catch(() => {})  // se bloqueado, a primeira interação inicia
    }).catch(() => {})
  }, [music?.file, music?.default_path]) // eslint-disable-line react-hooks/exhaustive-deps
}
