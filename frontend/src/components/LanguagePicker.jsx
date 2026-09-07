import { LANGUAGES, useT } from '../i18n/index.jsx'

// Selector de idioma. Los nombres van en su propio idioma a propósito: una
// lista traducida al idioma ACTUAL no le sirve a quien no entiende el idioma
// actual y quiere salir de él — que es justo quien lo busca.
//
// Vive en Ajustes, con la campanilla y los textos rápidos: es una preferencia
// del panel entero. Estuvo suelto en el pie del sidebar mientras fue el único.
export function LanguagePicker() {
  const { lang, setLang, t } = useT()
  return (
    <select
      value={lang}
      onChange={(e) => setLang(e.target.value)}
      title={t('lang.label')}
      aria-label={t('lang.label')}
      className="shrink-0 rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-xs text-gray-100 outline-none transition focus:border-panel-accent"
    >
      {LANGUAGES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  )
}
