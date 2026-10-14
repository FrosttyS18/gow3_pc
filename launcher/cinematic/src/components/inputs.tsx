import { useEffect, useRef, useState } from "react"
import { Choice } from "../bridge"

/* ============================== TOGGLE (Figma) ==============================
 * 1080p: 99×49.5, r 21.74, borda 1.23 #9F0000, círculo 42.55, somra
 *        0.82/2.05/1.39 rgba(0,0,0,.25), texto 15.74 Helvetica Light.
 * 720p:  66×33, r 14.5, círculo 28.37, texto 10.49.
 * OFF: fundo #000, círculo #9F0000 à ESQUERDA com SETA BRANCA →, "OFF" à direita.
 * ON:  fundo #9F0000, borda preta, círculo #FFF à DIREITA com SETA PRETA ←, "ON" à esquerda. */
const Arrow = ({ left }: { left: boolean }) => (
  <svg width="15" height="10" viewBox="0 0 16 10" aria-hidden="true"
    style={left ? { transform: "scaleX(-1)" } : undefined}>
    <path d="M1 5h11M8.5 1.2 12.8 5 8.5 8.8"
      stroke="currentColor" strokeWidth="1.7" fill="none"
      strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export function Toggle({ value, onChange, label }: {
  value: boolean
  onChange: (next: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={label}
      className={"toggle" + (value ? " on" : "")}
      onClick={() => onChange(!value)}
    >
      <span className="state" aria-hidden="true">{value ? "ON" : "OFF"}</span>
      <span className="knob" aria-hidden="true"><Arrow left={value} /></span>
    </button>
  )
}

/* ============================ DROPDOWN (Figma) =============================
 * 1080p: 377×49, r 4, borda 1.23 #9F0000, texto 15.74 branco, caret 12×9.
 * 720p:  251×33, r 2.7, texto 10.49, caret 8×6, padding 12px.
 * Lista totalmente estilizada (sem popup nativo): fundo preto, borda #9F0000,
 * hover legível, selecionado distinto, rolagem, teclado completo. */
export function Dropdown({ value, choices, onChange, label, width }: {
  value: string
  choices: Choice[]
  onChange: (next: string) => void
  label: string
  width?: number
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const selected = choices.findIndex((c) => c.value === value)

  useEffect(() => {
    if (!open) return
    const onDoc = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  useEffect(() => { if (open) setActive(Math.max(selected, 0)) }, [open]) // eslint-disable-line

  const pick = (index: number) => {
    const choice = choices[index]
    if (choice) onChange(choice.value)
    setOpen(false)
  }
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open && (event.key === "Enter" || event.key === " " || event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault()
      setOpen(true)
      return
    }
    if (!open) return
    if (event.key === "Escape") { event.preventDefault(); setOpen(false) }
    else if (event.key === "ArrowDown") { event.preventDefault(); setActive((a) => Math.min(a + 1, choices.length - 1)) }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (event.key === "Enter") { event.preventDefault(); pick(active) }
  }

  const current = choices[selected]
  return (
    <div className={"dropdown" + (open ? " open" : "")} ref={root}
      style={width ? { width } : undefined}>
      <button type="button" className="dropdown-box" aria-haspopup="listbox"
        aria-expanded={open} aria-label={label}
        onClick={() => setOpen(!open)} onKeyDown={onKeyDown}>
        <span className="dropdown-value">{current ? current.label : "—"}</span>
        <svg className="caret" width="8" height="6" viewBox="0 0 10 6" aria-hidden="true">
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.6"
            fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <ul className="dropdown-list" role="listbox" aria-label={label}>
          {choices.map((choice, index) => (
            <li key={choice.value} role="option" aria-selected={index === selected}
              className={"dropdown-option" + (index === active ? " active" : "")
                + (index === selected ? " selected" : "")}
              onMouseEnter={() => setActive(index)}
              onMouseDown={(e) => { e.preventDefault(); pick(index) }}>
              {choice.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ============================ CAMPOS AUXILIARES ============================ */

/** Campo de caminho: mostra o valor real e abre o seletor de pasta nativo. */
export function PathField({ value, onPick, placeholder }: {
  value: string
  onPick: () => void
  placeholder?: string
}) {
  return (
    <div className="pathfield">
      <span className="path">{value || placeholder || "—"}</span>
      <button type="button" className="action" onClick={onPick}>Escolher pasta</button>
    </div>
  )
}

/** Botão de ação discreto (Restaurar, Atualizar, Abrir, Limpar…). */
export function ActionButton({ children, onClick, disabled, danger }: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button type="button" className={"action" + (danger ? " danger" : "")}
      disabled={disabled} onClick={onClick}>
      {children}
    </button>
  )
}

/** Linha de configuração: rótulo, controle e descrição curta em pt-BR. */
export function Field({ label, hint, children, restart }: {
  label: string
  hint?: string
  children: React.ReactNode
  restart?: boolean
}) {
  return (
    <div className="field">
      <div className="field-head">
        <label>{label}</label>
        {children}
      </div>
      {hint && <p className="field-hint">{hint}{restart ? " Aplica-se ao iniciar o jogo." : ""}</p>}
    </div>
  )
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="settings-section">
      <h2>{title}</h2>
      <div className="settings-section-body">{children}</div>
    </section>
  )
}

/** Gancho utilitário: grava e recarrega o estado compartilhado. */
export function useSaver(refresh: () => void) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const run = async (op: () => Promise<unknown>) => {
    setSaving(true); setError("")
    try { await op(); refresh() }
    catch (e) { setError(String((e as Error).message ?? e)) }
    finally { setSaving(false) }
  }
  return { run, saving, error }
}

export async function pickFolderAndSet(key: string, refresh: () => void) {
  const path = await (window as unknown as {
    __GOW3_PICK_FOLDER__?: () => Promise<string | null>
  }).__GOW3_PICK_FOLDER__?.()
  if (path) {
    await (await import("../bridge")).bridge.setApp({ [key]: path }).then(refresh)
  }
}
