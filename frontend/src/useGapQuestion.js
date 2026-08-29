import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

// Cada cuánto se pregunta al servidor si hay algún hueco sin responder.
const SONDEO_MS = 60 * 1000

export const PREF_PREGUNTAR = 'muxspace.worklog.preguntar'

/** ¿Está encendido el interruptor de preguntar? Por defecto NO. */
export function leerPreguntar() {
  try {
    return localStorage.getItem(PREF_PREGUNTAR) === '1'
  } catch {
    // Sin almacenamiento (ventana privada) se queda apagado: interrumpir es
    // el comportamiento que hay que pedir, nunca el que toca por defecto.
    return false
  }
}

export function guardarPreguntar(valor) {
  try {
    localStorage.setItem(PREF_PREGUNTAR, valor ? '1' : '0')
  } catch {
    // Se pierde la preferencia y no pasa nada más.
  }
}

/**
 * La pregunta por los huecos que la jornada ha descontado.
 *
 * El servidor ya descuenta solo los ratos sin ninguna señal, así que esto NO
 * hace falta para que las horas salgan bien: sirve para corregir en caliente
 * el hueco que sí era trabajo, en vez de tener que acordarse al revisar los
 * tiempos. Por eso va detrás de un interruptor y viene apagado.
 *
 * Dos reglas, que son las que hacen que no se convierta en ruido:
 *
 * - **Pregunta la ventana que está delante.** Con cuatro ventanas de MuxSpace
 *   abiertas, el mismo banner en todas es la misma pregunta cuatro veces.
 * - **La respuesta es del servidor, no de la pestaña.** Al contestar se
 *   guarda (incluido el «estaba fuera», que no cambia ningún total), así que
 *   al cambiar de ventana la pregunta ya no está.
 *
 * @param {boolean} enabled - Solo con la sesión iniciada.
 */
export function useGapQuestion(enabled) {
  const [preguntar, setPreguntar] = useState(leerPreguntar)
  const [hueco, setHueco] = useState(null)

  const consultar = useCallback(async () => {
    if (!enabled || !preguntar || !document.hasFocus()) {
      setHueco(null)
      return
    }
    try {
      const datos = await api.workGaps({ desde: Date.now() - 86400_000 })
      const pendientes = (datos.gaps || []).filter((g) => !g.answered)
      // El más reciente: es el que el usuario acaba de vivir y el único sobre
      // el que puede contestar de memoria.
      setHueco(pendientes.length ? pendientes[pendientes.length - 1] : null)
    } catch {
      // Sin respuesta se deja lo que hubiera; el siguiente sondeo corrige.
    }
  }, [enabled, preguntar])

  useEffect(() => {
    consultar()
    const temporizador = setInterval(consultar, SONDEO_MS)
    // Al recuperar el foco es cuando de verdad hay alguien delante para
    // contestar; al perderlo, el banner se retira de esta ventana.
    window.addEventListener('focus', consultar)
    window.addEventListener('blur', consultar)
    return () => {
      clearInterval(temporizador)
      window.removeEventListener('focus', consultar)
      window.removeEventListener('blur', consultar)
    }
  }, [consultar])

  /** Contestar: `true` = estaba trabajando, `false` = estaba fuera. */
  const responder = useCallback(
    async (trabajando) => {
      const actual = hueco
      setHueco(null)
      if (!actual) return
      try {
        await api.claimGap(actual.start * 1000, actual.end * 1000, trabajando)
      } catch {
        // Si no se guarda, el hueco sigue descontado y la pregunta volverá.
        // Es el fallo correcto: no apunta horas que quizá no se trabajaron.
      }
    },
    [hueco],
  )

  const dejarDePreguntar = useCallback(() => {
    guardarPreguntar(false)
    setPreguntar(false)
    setHueco(null)
  }, [])

  return { hueco, preguntar, responder, dejarDePreguntar }
}
