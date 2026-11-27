import { useState } from 'react'

import { useT } from '../i18n/index.jsx'

// Fragmento de una búsqueda en las sesiones de Claude, pintado como TEXTO.
//
// El servidor ya lo trae partido en trozos `{text, mark, secret}`
// (`backend/claude_sessions.py: trocear_fragmento`): aquí no se interpreta
// nada ni se usa `dangerouslySetInnerHTML`. Una conversación puede contener
// `<script>` o HTML cualquiera y tiene que verse como lo que es, texto.
//
// Lo que parece una clave (sk-…, ghp_…, un token largo, el valor de
// `password=`) sale tapado con un botón «mostrar» POR TROZO: mirar un
// resultado no enseña una contraseña a quien tenga detrás.
export function ClaudeSnippet({ segments }) {
  const { t } = useT()
  const [shown, setShown] = useState(() => new Set())

  const toggle = (i) =>
    setShown((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })

  return (
    <p className="whitespace-pre-wrap break-words text-sm text-gray-300">
      {segments.map((seg, i) => {
        const hidden = seg.secret && !shown.has(i)
        const body = hidden ? null : seg.mark ? (
          <mark className="rounded bg-yellow-400/80 px-0.5 text-black">{seg.text}</mark>
        ) : (
          <span>{seg.text}</span>
        )
        if (!seg.secret) return <span key={i}>{body}</span>
        return (
          <span key={i}>
            {hidden ? (
              <span aria-hidden="true" className="select-none text-panel-muted">
                ••••••
              </span>
            ) : (
              body
            )}{' '}
            <button
              type="button"
              onClick={() => toggle(i)}
              className="inline-flex min-h-[2.25rem] items-center rounded border border-panel-border px-2 text-xs text-panel-muted hover:text-gray-100"
            >
              {hidden ? t('csessions.show_secret') : t('csessions.hide_secret')}
            </button>
          </span>
        )
      })}
    </p>
  )
}
