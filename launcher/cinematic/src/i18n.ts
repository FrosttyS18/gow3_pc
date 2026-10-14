import { createContext, useContext } from "react"

/** Tipos do dicionário de tradução exposto pela ponte (gow3_lang.table). */
export type LangTable = Record<string, string>

/** Contexto de idioma do launcher (NÃO do jogo — `language` do settings é o jogo).
 *  A troca é IMEDIATA: quem muda `ui_language` chama setLanguage, o contexto
 *  propaga e os componentes re-renderizam na hora (página, scroll, música e
 *  estados preservados — nada é reconstruído). */
export interface I18n {
  language: string
  setLanguage: (next: string) => void
  t: (english: string, ...args: (string | number)[]) => string
  tables: Record<string, LangTable>
}

export const I18nContext = createContext<I18n>({
  language: "en",
  setLanguage: () => {},
  t: (english) => english,
  tables: {},
})

export function useI18n() {
  return useContext(I18nContext)
}

/** Tradução: usa a tabela oficial (gow3_lang) quando a chave existe no idioma;
 *  caso contrário devolve o inglês. Args substituem {} na ordem. */
export function translate(table: LangTable, english: string, ...args: (string | number)[]) {
  let text = table[english] ?? english
  for (const arg of args) {
    text = text.replace("{}", String(arg))
  }
  return text
}
