import type { Page } from "../App"

/** Menu vertical fiel ao Figma, com as páginas REAIS do launcher original.
 *  "Gráficos" (experimental) entra após Display: precisa permanecer acessível. */
const ITEMS: { id: Page; label: string }[] = [
  { id: "display", label: "Display" },
  { id: "graphics", label: "Gráficos" },
  { id: "performance", label: "Performance" },
  { id: "game", label: "Game" },
  { id: "patches", label: "Patches" },
  { id: "mods", label: "Mods" },
  { id: "controls", label: "Controls" },
  { id: "advanced", label: "Advanced" },
  { id: "log", label: "Log" },
]

/** Hover/foco SEM CLIQUE: o texto cresce até o tamanho do Figma (18,49→25,65px),
 *  fica branco e acende — os vizinhos acompanham o reflow, como no frame ativo.
 *  Seleção é outro estado: o item ativo permanece maior/branco com a linha
 *  vermelha; hover sobre ele não amplia duas vezes (mesma fonte). */
export function NavMenu({ page, onNavigate }: { page: Page; onNavigate: (p: Page) => void }) {
  return (
    <nav className="nav" aria-label="Menu principal">
      {ITEMS.map(({ id, label }) => (
        <button
          key={id}
          className={page === id ? "active" : ""}
          onClick={() => onNavigate(page === id ? "home" : id)}
        >
          {label}
        </button>
      ))}
    </nav>
  )
}
