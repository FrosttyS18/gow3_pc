import { useEffect, useRef, useState } from "react"
import { bridge, BridgeState, Choice } from "../bridge"

function Segmented({ label, choices, value, onPick }: {
  label: string
  choices: Choice[]
  value: string
  onPick: (v: string) => void
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {choices.map((choice) => (
          <button
            key={choice.value}
            role="radio"
            aria-checked={choice.value === value}
            className={choice.value === value ? "on" : ""}
            onClick={() => onPick(choice.value)}
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function Select({ label, choices, value, onPick }: {
  label: string
  choices: Choice[]
  value: string
  onPick: (v: string) => void
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <select value={value} onChange={(e) => onPick(e.target.value)}>
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
    </div>
  )
}

/** Vídeo/Display — first REAL settings page: every control writes gow3.ini through
 *  the Python bridge (comments and foreign keys preserved by save_ini). */
export function DisplayPage({ ini, choices, onChanged }: {
  ini: BridgeState["ini"]
  choices: BridgeState["choices"]
  onChanged: () => void
}) {
  const [saved, setSaved] = useState(false)
  const flash = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(flash.current), [])

  const set = (key: string, value: string) => {
    bridge.setIni({ [key]: value }).then(() => {
      onChanged()
      setSaved(false)
      window.clearTimeout(flash.current)
      flash.current = window.setTimeout(() => setSaved(true), 60)
      window.setTimeout(() => setSaved(false), 1800)
    }).catch((e) => console.error("set_ini", e))
  }

  return (
    <section className="panel" aria-label="Configurações de vídeo">
      <h1>
        Display
        <span className={saved ? "saved show" : "saved"} style={{ float: "right", marginTop: 12 }}>
          ✓ gow3.ini
        </span>
      </h1>
      <p className="hint">Os valores entram no mesmo gow3.ini do port — comentários e chaves
        de terceiros são preservados pela mesma rotina do launcher original.</p>
      <div className="grid">
        <Segmented label="Modo de exibição" choices={choices.display_mode}
          value={ini.display_mode ?? "windowed"} onPick={(v) => set("display_mode", v)} />
        <Select label="Resolução de renderização" choices={choices.render_resolution}
          value={ini.render_resolution ?? "native"} onPick={(v) => set("render_resolution", v)} />
        <Segmented label="Taxa de quadros do motor" choices={choices.engine_fps}
          value={ini.engine_fps ?? "120"} onPick={(v) => set("engine_fps", v)} />
        <Select label="Limite de quadros" choices={choices.fps_limit}
          value={ini.fps_limit ?? "0"} onPick={(v) => set("fps_limit", v)} />
      </div>
      <div className="soon">
        Gráficos (FSR/sharpen), Performance avançada e as demais páginas chegam no M2 —
        nenhum controle fictício aqui.
      </div>
    </section>
  )
}
