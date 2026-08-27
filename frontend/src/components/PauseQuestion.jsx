import React from 'react'
import { useT } from '../i18n/index.jsx'
import { formatDuration } from '../worklog.js'

/**
 * La pregunta al volver de un hueco largo: «¿estabas trabajando o fuera?».
 *
 * Existe porque nadie se acuerda de marcar la pausa ANTES de levantarse, y
 * porque la duración del hueco no permite adivinarlo: medido sobre un día
 * real, un hueco de 87 minutos fue mitad trabajo, uno de 60 fue trabajo
 * entero y uno de 89 fue casi todo ausencia.
 *
 * No es un modal que bloquee: aparece abajo y se puede ignorar. Bloquear la
 * pantalla para cobrar el peaje de una pregunta administrativa es la forma
 * más rápida de que se conteste lo primero con tal de quitarla de en medio,
 * y una respuesta pulsada sin leer es peor que ninguna.
 */
export default function PauseQuestion({ hueco, onResponder }) {
  const { t } = useT()
  if (!hueco) return null
  const duracion = formatDuration(Math.round((hueco.hasta - hueco.desde) / 1000))

  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))]
                 -translate-x-1/2 rounded-lg border border-panel-border
                 bg-panel-surface p-4 shadow-lg"
    >
      <p className="text-sm text-gray-100">{t('pause.question', { time: duracion })}</p>
      <p className="mt-1 text-xs text-panel-muted">{t('pause.hint')}</p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => onResponder(false)}
          className="rounded border border-panel-accent bg-panel-accent/20 px-3 py-1
                     text-xs text-gray-100 transition hover:bg-panel-accent/30"
        >
          {t('pause.was_working')}
        </button>
        <button
          type="button"
          onClick={() => onResponder(true)}
          className="rounded border border-panel-border px-3 py-1 text-xs
                     text-panel-muted transition hover:text-gray-100"
        >
          {t('pause.was_away')}
        </button>
      </div>
    </div>
  )
}
