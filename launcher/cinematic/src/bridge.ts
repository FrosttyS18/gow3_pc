// Typed client for the Python bridge (launcher/cinematic/bridge/launcher_bridge.py),
// reached through the Tauri command `bridge_call` — the Python layer stays the single
// owner of every port rule (settings.json / gow3.ini / mods.json / patches.json / saves).

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

export interface BuiltinPatch { name: string; author: string | null; note: string | null; enabled: boolean }
export interface ExternalPatch { key: string; author: string | null; enabled: boolean }
export interface PatchesState {
  title_id: string | null
  version: string | null
  builtin: BuiltinPatch[]
  external: ExternalPatch[]
}

export interface ModsState {
  available: string[]
  order: string[]
  disabled: string[]
  conflicts: [string, string[]][]
  presets: string[]
}

export interface ControlRow {
  button: string
  ps_name: string
  default_key: string
  default_pad: string
  key: string
  pad: string
  remappable: boolean
}

export interface ControlsState {
  style: string
  styles: Record<string, Record<string, string>>
  rows: ControlRow[]
}

export interface BridgeState {
  version: string
  app: Record<string, string | number | boolean>
  controls_cfg: { controls: { key?: Record<string, string>; pad?: Record<string, string> }; pad_style: string }
  game_patches_cfg: Record<string, string[]>
  ini: Record<string, string>
  game: GameState
  music: MusicState
  choices: Record<string, Choice[]>
  patches: PatchesState
  mods: ModsState
  backups: { keep: number; names: string[] }
  controls: ControlsState
  running: boolean
  translations: Record<string, Record<string, string>>
}

export interface PlayStatus {
  running: boolean
  pid: number | null
  exit_code: number | null
  outcome: "error" | "finished" | "unknown" | null
  last_line: string
  tail: string
}

declare global {
  interface Window {
    __GOW3_BRIDGE__?: (request: string) => Promise<string>
    __GOW3_PICK_FOLDER__?: () => Promise<string | null>
    __GOW3_MUSIC_URL__?: (path: string) => Promise<string | null>
    __GOW3_OPEN__?: (path: string) => Promise<void>
  }
}

/** Gravações no MESMO arquivo nunca correm concorrentes: cada setApp/preset/
 *  modsSet entra numa fila única — o último clique sempre vence, sem corrida
 *  entre processos da ponte lendo/escrevendo settings.json ao mesmo tempo. */
let writeChain: Promise<unknown> = Promise.resolve()
function enqueueWrite<T>(op: () => Promise<T>): Promise<T> {
  const next = writeChain.then(op, op)
  writeChain = next.catch(() => {})
  return next
}

async function call<T>(request: Record<string, unknown>): Promise<T> {
  if (!window.__GOW3_BRIDGE__) {
    throw new Error("ponte indisponível (fora do app Tauri)")
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
    enqueueWrite(() => call<{ ok: true }>({ cmd: "set_app", values })),
  setGamePatches: (names: string[]) =>
    call<{ ok: true }>({ cmd: "set_game_patches", names }),
  setExternalPatches: (enabled: string[], disabled: string[]) =>
    call<{ ok: true }>({ cmd: "set_external_patches", enabled, disabled }),
  modsSet: (order: string[], disabled: string[]) =>
    call<{ ok: true }>({ cmd: "mods_set", order, disabled }),
  preset: (name: string, op: "save" | "load" | "delete") =>
    call<{ ok: true; presets?: string[] }>({ cmd: "preset", name, op }),
  backupsList: () => call<{ names: string[] }>({ cmd: "backups_list" }),
  backupRestore: (name: string) =>
    call<{ ok: true; safety: string | null; names: string[] }>({ cmd: "backup_restore", name }),
  controlsSet: (key: Record<string, string>, pad: Record<string, string>, pad_style: string) =>
    call<{ ok: true }>({ cmd: "controls_set", key, pad, pad_style }),
  clearCache: () => call<{ ok: true }>({ cmd: "clear_cache" }),
  updateCheck: () =>
    call<{ current: string; latest: string; page: string; newer: boolean }>({ cmd: "update_check" }),
  logRead: () =>
    call<{ sources: { name: string; path: string; text: string }[]; running: boolean }>({ cmd: "log_read" }),
  /** JOGAR (hotfix P0): o Rust recebe a especificação da ponte (worker persistente),
   * inicia a sessão e vigia o fim por EVENTO do kernel (Job Object de sessão) —
   * nenhum processo novo por clique, nenhum polling durante o jogo. */
  play: () => {
    const tauri = (window as unknown as {
      __TAURI__?: { core: { invoke: (cmd: string) => Promise<{ ok: boolean; pid: number; log: string }> } }
    }).__TAURI__
    if (!tauri) throw new Error("fora do app Tauri")
    return tauri.core.invoke("game_start")
  },
  playStatus: () => call<PlayStatus>({ cmd: "play_status" }),
  pickFolder: () => window.__GOW3_PICK_FOLDER__?.() ?? Promise.resolve(null),
  openInExplorer: (path: string) =>
    window.__GOW3_OPEN__?.(path) ?? Promise.reject(new Error("fora do app")),
  musicDataUrl: (path: string) => window.__GOW3_MUSIC_URL__?.(path) ?? Promise.resolve(null),
}
