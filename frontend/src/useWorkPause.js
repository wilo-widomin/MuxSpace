import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'

// Hueco sin latidos a partir del cual el panel pregunta qué era. Por debajo de
// media hora no vale la pena preguntar: son ausencias cortas que caen dentro
// del margen de error del registro, y una pregunta que salta cada rato se
// contesta sin leerla, que es peor que no preguntar.
export const HUECO_PREGUNTABLE_MS = 30 * 60 * 1000

// Cada cuánto se comprueba si hay una pausa abierta en el servidor. La pausa
// vive en el servidor y no en la pestaña a propósito: te vas del ordenador,
// vuelves desde la tableta, y la pausa tiene que seguir siendo la misma.
const SONDEO_MS = 60 * 1000

/**
 * Las pausas del registro de tiempo.
 *
 * En el modo 'workday' la jornada cuenta entera y lo que hay que declarar es
 * la **ausencia**. Este hook lleva dos cosas: el botón de «me voy / ya estoy»
 * y la pregunta al volver de un hueco largo.
 *
 * La pregunta existe porque nadie se acuerda de marcar la pausa ANTES de
 * levantarse. Al volver sí puede decir qué era ese hueco, y entonces se
 * recorta con la hora real en vez de con una regla inventada.
 *
 * @param {boolean} enabled - Solo con la sesión iniciada.
 */
export function useWorkPause(enabled) {
  const [pausado, setPausado] = useState(false)
  const [modo, setModo] = useState(null)
  // El hueco pendiente de explicar: {desde, hasta} o null.
  const [pregunta, setPregunta] = useState(null)
  // El último latido por el que ya se preguntó. Sin esto, cada sondeo
  // repetiría la misma pregunta hasta que se contestara.
  const preguntadoRef = useRef(0)

  const consultar = useCallback(async () => {
    if (!enabled) return
    try {
      const datos = await api.workPauses({ desde: Date.now() - 86400_000 })
      setModo(datos.mode)
      setPausado(datos.pauses.some((p) => p.open))

      // La ausencia se detecta por la FALTA DE LATIDOS, no por un salto del
      // reloj. Mirar el reloj solo cazaría el portátil que se suspende, y la
      // ausencia normal —irse a comer dejando el panel abierto— no mueve
      // ningún reloj: los temporizadores siguen corriendo tan campantes con
      // nadie delante.
      const ultimo = datos.last_slot ? datos.last_slot * 1000 : null
      const ahora = Date.now()
      if (!ultimo) return
      const hueco = ahora - ultimo
      const yaCubierto = datos.pauses.some(
        (p) => p.end !== null && p.end * 1000 >= ultimo,
      )
      if (
        hueco >= HUECO_PREGUNTABLE_MS &&
        !yaCubierto &&
        // Un hueco ya preguntado no se vuelve a preguntar aunque se ignore la
        // pregunta: insistir es la forma más rápida de que se conteste mal.
        ultimo !== preguntadoRef.current
      ) {
        preguntadoRef.current = ultimo
        setPregunta({ desde: ultimo, hasta: ahora })
      }
    } catch {
      // Sin respuesta se deja el estado como estaba: el botón sigue siendo
      // usable y el siguiente sondeo lo corrige.
    }
  }, [enabled])

  useEffect(() => {
    consultar()
    const temporizador = setInterval(consultar, SONDEO_MS)
    // Volver a la pestaña es el momento en que de verdad interesa mirar: es
    // cuando el usuario ha vuelto y puede contestar.
    window.addEventListener('focus', consultar)
    return () => {
      clearInterval(temporizador)
      window.removeEventListener('focus', consultar)
    }
  }, [consultar])

  const alternarPausa = useCallback(async () => {
    try {
      if (pausado) {
        await api.workResume()
        setPausado(false)
      } else {
        await api.workPause()
        setPausado(true)
      }
    } catch {
      // Si falla, el sondeo devuelve el estado real en menos de un minuto.
      consultar()
    }
  }, [pausado, consultar])

  /** Responder a la pregunta: `true` = estaba fuera, `false` = trabajando. */
  const responder = useCallback(
    async (estabaFuera) => {
      const hueco = pregunta
      setPregunta(null)
      if (!hueco || !estabaFuera) return
      try {
        await api.markPause(hueco.desde, hueco.hasta)
      } catch {
        // Un hueco sin marcar cuenta como trabajo. Es el sesgo que este modo
        // acepta a cambio de no perder jornadas enteras, y siempre se puede
        // corregir después desde el dashboard.
      }
    },
    [pregunta],
  )

  return { pausado, modo, pregunta, alternarPausa, responder }
}
