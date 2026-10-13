// Typed client for the Python bridge (launcher/cinematic/bridge/launcher_bridge.py),
// reached through the Tauri command `bridge_call` — the Python layer stays the single
// owner of every port rule (settings.json / gow3.ini / run.py).

export interface Choice { value: string; label: string }

export interface GameState {
  found: boolean
  folder: string
  title_id: string | null
  patch_profile: boolean
  summary: string
  missing_files: string[]
}

export interface MusicState {
  default_path: string | null
  file: string
  volume: number
  muted: boolean
}

export interface BridgeState {
  app: Record<string, string | number | boolean>
  ini: Record<string, string>
  game: GameState
  music: MusicState
  choices: {
    display_mode: Choice[]
    render_resolution: Choice[]
    engine_fps: Choice[]
    fps_limit: Choice[]
  }
}

export interface PlayStatus {
  running: boolean
  pid: number | null
  outcome: "error" | "finished" | null
  tail: string
}

declare global {
  interface Window {
    __GOW3_BRIDGE__?: (request: string) => Promise<string>
    __GOW3_PICK_MUSIC__?: () => Promise<string | null>
    __GOW3_MUSIC_URL__?: (path: string) => Promise<string | null>
  }
}

async function call<T>(request: Record<string, unknown>): Promise<T> {
  if (!window.__GOW3_BRIDGE__) {
    throw new Error("bridge unavailable (fora do app Tauri)")
  }
  const raw = await window.__GOW3_BRIDGE__(JSON.stringify(request))
  const response = JSON.parse(raw) as T & { error?: string }
  if (response.error) throw new Error(response.error)
  return response
}

export const bridge = {
  state: () => call<BridgeState>({ cmd: "state" }),
  setIni: (values: Record<string, string | boolean>) =>
    call<{ ok: true; ini: Record<string, string> }>({ cmd: "set_ini", values }),
  setApp: (values: Record<string, string | number | boolean>) =>
    call<{ ok: true }>({ cmd: "set_app", values }),
  play: () => call<{ ok: true; pid: number; log: string }>({ cmd: "play" }),
  playStatus: () => call<PlayStatus>({ cmd: "play_status" }),
  pickMusic: () => window.__GOW3_PICK_MUSIC__?.() ?? Promise.resolve(null),
  musicDataUrl: (path: string) => window.__GOW3_MUSIC_URL__?.(path) ?? Promise.resolve(null),
}
