import { useState } from 'react'

import { useT } from '../i18n/index.jsx'
import { SCALES, readScale, setScale } from '../uiScale.js'

// Selector del tamaño del panel en este aparato. Hermano del de idioma: un
// desplegable corto que se resuelve en la misma fila de Ajustes.
export function ScalePicker() {
  const { t } = useT()
  const [scale, setLocal] = useState(readScale)
  return (
    <select
      value={scale}
      onChange={(e) => {
        const next = Number(e.target.value)
        setLocal(next)
        setScale(next)
      }}
      title={t('scale.label')}
      aria-label={t('scale.label')}
      className="shrink-0 rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-xs text-gray-100 outline-none transition focus:border-panel-accent"
    >
      {SCALES.map((s) => (
        <option key={s} value={s}>
          {`${Math.round(s * 100)} %`}
        </option>
      ))}
    </select>
  )
}
