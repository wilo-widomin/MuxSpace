import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import {
  ACTIVITY_EVENTS,
  HEARTBEAT_MS,
  isWorking,
  manualExpired,
} from './worklog.js'

/**
 * Reloj de trabajo de esta pestaña: late al servidor mientras hay actividad.
 *
 * Los oyentes van en `window`, **pasivos** y solo escriben en un ref: si cada
 * `mousemove` provocara un render, el arrastre de ventanas y las terminales lo
 * notarían. El estado de React solo cambia cuando cambia el indicador (una vez
 * cada 30 s como mucho).
 *
 * Nada de esto mira el WebSocket del terminal, y es a propósito: la salida del
 * PTY no es actividad (ver `worklog.js`).
 *
 * @param {string} space - Espacio que mira esta pestaña.
 * @param {string|null} session - Sesión que el usuario tiene activa.
 * @param {boolean} enabled - Solo se cuenta con la sesión iniciada.
 */
export function useWorkClock(space, session, enabled) {
  const [activo, setActivo] = useState(false)
  const [manual, setManual] = useState(false)

  const lastInputRef = useRef(Date.now())
  const manualDesdeRef = useRef(0)
  // Espacio y sesión en refs: el latido corre en un intervalo que no debe
  // reiniciarse cada vez que el usuario cambia de terminal.
  const spaceRef = useRef(space)
  spaceRef.current = space
  const sessionRef = useRef(session)
  sessionRef.current = session

  useEffect(() => {
    const marcar = () => {
      lastInputRef.current = Date.now()
    }
    for (const evento of ACTIVITY_EVENTS) {
      window.addEventListener(evento, marcar, { passive: true, capture: true })
    }
    return () => {
      for (const evento of ACTIVITY_EVENTS) {
        window.removeEventListener(evento, marcar, { capture: true })
      }
    }
  }, [])

  const alternarManual = useCallback(() => {
    setManual((actual) => {
      const siguiente = !actual
      manualDesdeRef.current = siguiente ? Date.now() : 0
      // Encenderlo cuenta como entrada: si el usuario lo pulsa, está delante.
      if (siguiente) lastInputRef.current = Date.now()
      return siguiente
    })
  }, [])

  useEffect(() => {
    if (!enabled) {
      setActivo(false)
      return undefined
    }

    const latir = async () => {
      const ahora = Date.now()
      const estado = {
        hasFocus: document.hasFocus(),
        lastInput: lastInputRef.current,
        manual,
        manualSince: manualDesdeRef.current,
      }
      if (manualExpired(estado, ahora)) {
        setManual(false)
        manualDesdeRef.current = 0
        estado.manual = false
      }
      const trabajando = isWorking(estado, ahora)
      setActivo(trabajando)
      if (!trabajando) return
      try {
        await api.workBeat(spaceRef.current, sessionRef.current)
      } catch {
        // Un latido perdido cuesta 30 segundos y nada más. Reintentar sería
        // recuperar un instante que ya pasó: la siguiente ranura es la que
        // importa.
      }
    }

    latir()
    const temporizador = setInterval(latir, HEARTBEAT_MS)
    return () => clearInterval(temporizador)
  }, [enabled, manual])

  return { activo, manual, alternarManual }
}
