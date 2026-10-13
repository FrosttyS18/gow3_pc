import type { Page } from "../App"

const ITEMS: { id: Page; label: string }[] = [
  { id: "display", label: "Display" },
  { id: "performance", label: "Performance" },
  { id: "game", label: "Game" },
  { id: "patches", label: "Patches" },
  { id: "mods", label: "Mods" },
  { id: "controls", label: "Controls" },
  { id: "advanced", label: "Advanced" },
  { id: "log", label: "Log" },
]

/** The Figma vertical menu: hover/focus grows the item ~12% and lights the letters
 *  with warm firelight (pure transform — zero layout shift); the active item keeps
 *  its identity with white text and one thin blood divider. */
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
