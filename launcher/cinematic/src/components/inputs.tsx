import { useState } from "react"
import { Choice, bridge } from "../bridge"

/** Toggle do Figma (99×49.5 @1080 → 66×33 @720): OFF = fundo preto, borda/círculo
 *  #9F0000, texto OFF; ON = fundo #9F0000, círculo branco, texto ON. Estado real,
 *  teclado (role=switch + Space) e transição suave. */
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
      <span className="knob" aria-hidden="true">
        <svg width="11" height="11" viewBox="0 0 24 24">
          {value
            ? <path fill="currentColor" d="M7 4v16l13-8z" />
            : <path fill="none" stroke="currentColor" strokeWidth="3" d="M5 12h14" />}
        </svg>
      </span>
      <span className="state" aria-hidden="true">{value ? "ON" : "OFF"}</span>
    </button>
  )
}

/** Dropdown do Figma (377×49 @1080 → 251×33 @720): fundo #000, borda #9F0000,
 *  texto branco. Os valores vêm EXCLUSIVAMENTE das listas reais do backend. */
export function Dropdown({ value, choices, onChange, label }: {
  value: string
  choices: Choice[]
  onChange: (next: string) => void
  label: string
}) {
  return (
    <div className="dropdown">
      <select value={value} aria-label={label} onChange={(e) => onChange(e.target.value)}>
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
      <svg className="caret" width="9" height="6" viewBox="0 0 10 6" aria-hidden="true">
        <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      </svg>
    </div>
  )
}

/** Campo de caminho: mostra o valor real e abre o seletor de pasta nativo. */
export function PathField({ value, onPick, placeholder }: {
  value: string
  onPick: () => void
  placeholder?: string
}) {
  return (
    <div className="pathfield">
      <span className="path">{value || placeholder || "—"}</span>
      <button type="button" onClick={onPick}>Escolher pasta</button>
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
  const path = await bridge.pickFolder()
  if (path) {
    await bridge.setApp({ [key]: path }).then(refresh)
  }
}
