import { useId, useState } from "react"

/** Tooltip do design system — substitui o tooltip NATIVO do navegador (title),
 *  que ignora cores/tipografia do launcher. Fundo preto translúcido, borda
 *  vermelha discreta, tipografia leve, hover E foco por teclado, ARIA completa
 *  (aria-describedby) e posicionamento que não cobre o acionador. */
export function Tooltip({ text, children }: {
  text: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span className={"tooltip-host" + (open ? " open" : "")}
      aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={() => setOpen(false)}>
      {children}
      <span className="tooltip-tip" role="tooltip" id={id}>{text}</span>
    </span>
  )
}
