import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { ACTIVITY_EVENTS, HEARTBEAT_MS, isWorking, manualExpired } from './worklog.js'

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
  // Última renovación del modo declarado. Se reinicia con cualquier entrada
  // tuya y al volver a esta pestaña: por eso el tope es "renovable" y no un
  // límite duro de media hora de trabajo.
  const manualDesdeRef = useRef(0)
  const manualRef = useRef(false)
  manualRef.current = manual
  // ¿El sistema dice que no estás delante? `undefined` mientras no se sepa.
  const ausenteRef = useRef(undefined)
  const detectorRef = useRef(null)
  // Espacio y sesión en refs: el latido corre en un intervalo que no debe
  // reiniciarse cada vez que el usuario cambia de terminal.
  const spaceRef = useRef(space)
  spaceRef.current = space
  const sessionRef = useRef(session)
  sessionRef.current = session

  useEffect(() => {
    const marcar = () => {
      lastInputRef.current = Date.now()
      // Trabajar en el panel renueva el modo declarado: si estás aquí, la
      // media hora de gracia vuelve a empezar.
      if (manualRef.current) manualDesdeRef.current = Date.now()
    }
    for (const evento of ACTIVITY_EVENTS) {
      window.addEventListener(evento, marcar, { passive: true, capture: true })
    }
    // Volver a la pestaña también renueva, aunque todavía no toques nada.
    window.addEventListener('focus', marcar)
    return () => {
      for (const evento of ACTIVITY_EVENTS) {
        window.removeEventListener(evento, marcar, { capture: true })
      }
      window.removeEventListener('focus', marcar)
    }
  }, [])

  // Detección de presencia del navegador (Chrome, con permiso y en contexto
  // seguro). Solo se usa para APAGAR: dice si te has ido de la máquina o si
  // la pantalla está bloqueada mientras el modo declarado sigue encendido.
  // Sin ella, lo único que protege es la caducidad — que ya es suficiente,
  // así que no se pide permiso salvo al encender el modo.
  const vigilarPresencia = useCallback(async () => {
    if (detectorRef.current || !('IdleDetector' in window)) return
    try {
      const permiso = await window.IdleDetector.requestPermission()
      if (permiso !== 'granted') return
      const detector = new window.IdleDetector()
      detector.addEventListener('change', () => {
        ausenteRef.current =
          detector.userState === 'idle' || detector.screenState === 'locked'
      })
      await detector.start({ threshold: 60_000 })
      detectorRef.current = detector
    } catch {
      // Sin permiso, sin API o en un contexto no seguro: se sigue con la
      // caducidad como única red. No es motivo para no dejar contar.
    }
  }, [])

  const alternarManual = useCallback(() => {
    setManual((actual) => {
      const siguiente = !actual
      manualDesdeRef.current = siguiente ? Date.now() : 0
      if (siguiente) {
        // Encenderlo cuenta como entrada: si lo pulsas, estás delante.
        lastInputRef.current = Date.now()
        ausenteRef.current = undefined
        // El clic es el gesto del usuario que la API de presencia exige para
        // poder pedir permiso.
        vigilarPresencia()
      }
      return siguiente
    })
  }, [vigilarPresencia])

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
        userAway: ausenteRef.current,
      }
      if (manualExpired(estado, ahora)) {
        setManual(false)
        manualDesdeRef.current = 0
        estado.manual = false
      }
      const modo = isWorking(estado, ahora)
      setActivo(Boolean(modo))
      if (!modo) return
      try {
        await api.workBeat(spaceRef.current, sessionRef.current, modo)
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

  // El detector de presencia sobrevive a los cambios de estado, así que se
  // suelta al desmontar y no en cada latido.
  useEffect(() => {
    return () => {
      detectorRef.current = null
    }
  }, [])

  return { activo, manual, alternarManual }
}
