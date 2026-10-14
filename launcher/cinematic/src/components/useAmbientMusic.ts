import { useEffect, useRef } from "react"
import { bridge, MusicState } from "../bridge"

/** Música ambiente — M1.7: o jogo MANDA. Ao clicar JOGAR a música PAUSA de forma
 *  DETERMINÍSTICA (audio.pause() imediato, NUNCA via rAF/fade para o estado "silêncio
 *  durante o jogo"); o fade é apenas cosmético antes da pausa. Nenhum callback
 *  atrasado (carregamento do MP3, pointerdown, restore) pode reiniciar a música
 *  enquanto o jogo estiver em execução ou a janela estiver oculta. Volume fixo
 *  1% (0.01) — única constante. Persiste SOMENTE ambient_muted. */
export const MUSIC_FIXED_VOLUME = 0.01

export function useAmbientMusic(music: MusicState | undefined, muted: boolean, gamePhase: string) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const mutedRef = useRef(muted)
  const gamePhaseRef = useRef(gamePhase)
  const fadeToken = useRef(0)
  mutedRef.current = muted
  gamePhaseRef.current = gamePhase

  /** Condição para poder tocar: não mudo, jogo não rodando, janela visível. */
  const mayPlay = () =>
    !mutedRef.current &&
    gamePhaseRef.current !== "preparing" &&
    gamePhaseRef.current !== "running"

  const applyVolume = () => {
    if (audio.current) audio.current.volume = mutedRef.current ? 0 : MUSIC_FIXED_VOLUME
  }

  const safePlay = () => {
    if (audio.current && audio.current.src && mayPlay()) {
      applyVolume()
      audio.current.play().catch(() => {})
    }
  }

  useEffect(() => {
    const element = new Audio()
    element.loop = true
    audio.current = element
    ;(window as unknown as { __gow3Audio?: HTMLAudioElement }).__gow3Audio = element

    const fadeOut = () => {
      // fade cosmético seguido de PAUSE determinístico — o rAF nunca é a garantia
      const token = ++fadeToken.current
      const start = element.volume
      const beganAt = performance.now()
      element.pause() // <-- determinístico: o áudio para AGORA, o fade é só o volume
      element.volume = start
      const step = () => {
        if (token !== fadeToken.current) return
        const t = Math.min(1, (performance.now() - beganAt) / 1200)
        element.volume = start * (1 - t)
        if (t < 1) requestAnimationFrame(step)
        else element.volume = 0
      }
      requestAnimationFrame(step)
    }

    const stopForGame = () => {
      fadeToken.current++ // cancela qualquer restore/fade em andamento
      element.pause()     // determinístico
      element.volume = 0
    }

    const restore = () => {
      fadeToken.current++
      if (!mayPlay()) return // jogo rodando ou mudo: música continua parada
      applyVolume()
      safePlay()
    }

    const kick = () => { if (mayPlay()) safePlay() }

    window.addEventListener("gow3:fade-music", fadeOut)
    window.addEventListener("gow3:stop-music", stopForGame)
    window.addEventListener("gow3:restore-music", restore)
    window.addEventListener("pointerdown", kick)
    return () => {
      window.removeEventListener("gow3:fade-music", fadeOut)
      window.removeEventListener("gow3:stop-music", stopForGame)
      window.removeEventListener("gow3:restore-music", restore)
      window.removeEventListener("pointerdown", kick)
      fadeToken.current++
      element.pause()
      audio.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // mudanças de fase do jogo: preparar/executar = PAUSA determinística; fim = restore se permitido
  useEffect(() => {
    if (!audio.current) return
    if (gamePhase === "preparing" || gamePhase === "running") {
      fadeToken.current++
      audio.current.pause()
      audio.current.volume = 0
    } else if (gamePhase === "idle" || gamePhase === "error") {
      // restore somente se não mudo e a janela não foi ocultada para close_on_play
      if (!mutedRef.current && !document.hidden) {
        applyVolume()
        safePlay()
      }
    }
  }, [gamePhase])

  // mute/unmute
  useEffect(() => {
    if (!audio.current) return
    if (muted) {
      audio.current.pause()
      audio.current.volume = 0
    } else if (mayPlay()) {
      applyVolume()
      safePlay()
    }
  }, [muted])

  // carrega a faixa UMA vez por caminho — o play() só acontece se mayPlay()
  useEffect(() => {
    if (!music || !audio.current) return
    const path = music.file || music.default_path
    if (!path) return
    bridge.musicDataUrl(path).then((url) => {
      if (!url || !audio.current) return
      audio.current.src = url
      if (mayPlay()) {
        applyVolume()
        audio.current.play().catch(() => {})
      }
    }).catch(() => {})
  }, [music?.file, music?.default_path]) // eslint-disable-line react-hooks/exhaustive-deps
}
