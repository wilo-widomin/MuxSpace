import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

// Cada cuánto se comprueba si hay una pausa abierta en el servidor. La pausa
// vive en el servidor y no en la pestaña a propósito: te vas del ordenador,
// vuelves desde la tableta, y la pausa tiene que seguir siendo la misma.
const SONDEO_MS = 60 * 1000

/**
 * El botón de «me voy / ya estoy» del registro de tiempo.
 *
 * Solo tiene sentido en el modo 'workday', donde la jornada cuenta entera. Es
 * para la ausencia CORTA —bajar a por café, media hora de recado—: los huecos
 * largos los descuenta ya el servidor por su cuenta, sin preguntar nada, y se
 * corrigen en la vista de tiempos.
 *
 * @param {boolean} enabled - Solo con la sesión iniciada.
 */
export function useWorkPause(enabled) {
  const [pausado, setPausado] = useState(false)
  const [modo, setModo] = useState(null)

  const consultar = useCallback(async () => {
    if (!enabled) return
    try {
      const datos = await api.workPauses({ desde: Date.now() - 86400_000 })
      setModo(datos.mode)
      setPausado(datos.pauses.some((p) => p.open))
    } catch {
      // Sin respuesta se deja el estado como estaba: el botón sigue siendo
      // usable y el siguiente sondeo lo corrige.
    }
  }, [enabled])

  useEffect(() => {
    consultar()
    const temporizador = setInterval(consultar, SONDEO_MS)
    // Volver a la pestaña es el momento en que de verdad interesa mirar: es
    // cuando el usuario ha vuelto y el botón puede estar mintiendo.
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

  return { pausado, modo, alternarPausa }
}
