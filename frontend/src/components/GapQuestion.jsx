import React from 'react'
import { useT } from '../i18n/index.jsx'
import { formatDuration, formatTime } from '../worklog.js'

/**
 * La pregunta por un hueco que la jornada ha descontado.
 *
 * Solo aparece con el interruptor encendido (ver `useGapQuestion`), y solo en
 * la ventana que tiene el foco. No es un modal: aparece abajo y se puede
 * ignorar. Bloquear la pantalla para cobrar el peaje de una pregunta
 * administrativa es la forma más rápida de que se conteste lo primero con tal
 * de quitarla de en medio, y una respuesta pulsada sin leer es peor que
 * ninguna.
 *
 * Ignorarla no pierde nada: el hueco sigue descontado y se puede recuperar
 * después desde la vista de tiempos.
 */
export default function GapQuestion({ hueco, onResponder, onNoPreguntar }) {
  const { t } = useT()
  if (!hueco) return null

  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))]
                 -translate-x-1/2 rounded-lg border border-panel-border
                 bg-panel-surface p-4 shadow-lg"
    >
      <p className="text-sm text-gray-100">
        {t('gap.question', { time: formatDuration(hueco.seconds) })}
      </p>
      <p className="mt-1 text-xs text-panel-muted">
        {t('gap.hint', {
          from: formatTime(hueco.start),
          to: formatTime(hueco.end),
        })}
      </p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onResponder(true)}
          className="rounded border border-panel-accent bg-panel-accent/20 px-3 py-1
                     text-xs text-gray-100 transition hover:bg-panel-accent/30"
        >
          {t('gap.was_working')}
        </button>
        <button
          type="button"
          onClick={() => onResponder(false)}
          className="rounded border border-panel-border px-3 py-1 text-xs
                     text-panel-muted transition hover:text-gray-100"
        >
          {t('gap.was_away')}
        </button>
        <button
          type="button"
          onClick={onNoPreguntar}
          className="ml-auto text-xs text-panel-muted underline-offset-2
                     hover:text-gray-100 hover:underline"
        >
          {t('gap.never_ask')}
        </button>
      </div>
    </div>
  )
}
