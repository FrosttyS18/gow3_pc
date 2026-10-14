import React from "react"
import ReactDOM from "react-dom/client"
import App from "./App"
import "./styles/global.css"

// Wire the real Tauri bridge when running inside the app; in a plain browser
// (design preview) a local mock keeps the UI explorable WITHOUT touching any
// real configuration file.
function mockBridge() {
  const ini: Record<string, string> = {
    display_mode: "borderless", render_resolution: "native", engine_fps: "240", fps_limit: "0",
  }
  const state = {
    version: "2.1.8", app: {}, controls_cfg: { controls: {}, pad_style: "playstation" },
    game_patches_cfg: {}, ini,
    game: { found: true, folder: "F:\\GOW3\\…", title_id: "CUSA01623", patch_profile: true,
            summary: "Native (1080p) · 120 FPS engine · 2 patches", missing_files: [] },
    music: { default_path: null, file: "", volume: 0.55, muted: false },
    choices: {
      display_mode: [{ value: "windowed", label: "Windowed" }, { value: "borderless", label: "Borderless" }, { value: "fullscreen", label: "Fullscreen" }],
      render_resolution: [{ value: "native", label: "Native (1080p)" }, { value: "720p", label: "720p" }, { value: "1440p", label: "1440p" }, { value: "4K", label: "4K" }],
      engine_fps: [{ value: "60", label: "60 (original)" }, { value: "120", label: "120" }, { value: "240", label: "240" }],
      fps_limit: [{ value: "60", label: "60" }, { value: "120", label: "120" }, { value: "0", label: "Unlimited" }],
    },
    patches: { title_id: "CUSA01623", version: "01.02",
      builtin: [{ name: "60 FPS", author: null, note: null, enabled: true }], external: [] },
    mods: { available: ["Exemplo"], order: ["Exemplo"], disabled: [], conflicts: [], presets: [] },
    backups: { keep: 10, names: [] },
    controls: { style: "playstation", styles: { playstation: { a: "Cruz" } }, rows: [] },
    fsr4: { installed: 44, total: 44, missing: 0, folder: "fsr4_shaders" },
    running: false,
  }
  window.__GOW3_BRIDGE__ = async (request: string) => {
    const parsed = JSON.parse(request) as { cmd: string; values?: Record<string, string> }
    if (parsed.cmd === "state") return JSON.stringify(state)
    if (parsed.cmd === "set_ini") {
      Object.assign(ini, parsed.values)
      return JSON.stringify({ ok: true, ini })
    }
    return JSON.stringify({ ok: true })
  }
}

async function boot() {
  if ((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) {
    const { invoke } = await import("@tauri-apps/api/core")
    window.__GOW3_BRIDGE__ = (request: string) => invoke<string>("bridge_call", { request })
    window.__GOW3_PICK_FOLDER__ = () => invoke<string | null>("pick_folder")
    window.__GOW3_OPEN__ = (path: string) => invoke<void>("open_in_explorer", { path })
    window.__GOW3_MUSIC_URL__ = (path: string) => invoke<string | null>("music_data_url", { path })
  } else {
    mockBridge()
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}

void boot()
