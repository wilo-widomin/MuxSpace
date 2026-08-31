import { useEffect, useRef } from 'react'

// Escucha el bus de eventos del backend (`/api/events`): un WebSocket por
// pestaña, aparte de los de las terminales.
//
// Por qué no basta el sondeo de `/api/sessions`: se detiene con la pestaña
// oculta (ver `loadSessions` en App.jsx), que es justo cuando el usuario
// necesita enterarse de que una sesión le reclama. Y aunque no se detuviera,
// ocho segundos de retraso convierten una campanilla en un recordatorio.
//
// El WebSocket **no es la fuente de verdad**: el estado de cada aviso viaja
// en el listado de sesiones. Esto solo adelanta la noticia, así que perder la
// conexión un rato degrada el aviso a "llega con el siguiente sondeo" y nunca
// a "no llega".

// Espera antes de reintentar, en milisegundos. Crece hasta el tope para no
// martillear un backend que está caído, pero el primer reintento es rápido:
// la caída típica no es un backend muerto, es la tablet que vuelve de
// suspensión y quiere su conexión de vuelta ya.
const RECONNECT_MS = [500, 1000, 2000, 5000, 10000]

export function useAttentionEvents(onEvent) {
  // Ref espejo: el callback cambia en cada render de App y el efecto no debe
  // reabrir el WebSocket por eso.
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    let ws = null
    let reintento = null
    let intentos = 0
    let vivo = true

    const conectar = () => {
      if (!vivo) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      try {
        ws = new WebSocket(`${proto}//${window.location.host}/api/events`)
      } catch {
        programarReintento()
        return
      }
      ws.onopen = () => {
        intentos = 0
      }
      ws.onmessage = (ev) => {
        let msg
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        // El latido solo existe para que el proxy no corte la conexión por
        // silencio; no dice nada de ninguna sesión.
        if (!msg || msg.type === 'ping') return
        onEventRef.current?.(msg)
      }
      ws.onclose = () => {
        ws = null
        programarReintento()
      }
      // `onerror` no hace falta: todo error acaba en `onclose`, y manejar los
      // dos reconectaría por duplicado.
    }

    const programarReintento = () => {
      if (!vivo || reintento) return
      const espera = RECONNECT_MS[Math.min(intentos, RECONNECT_MS.length - 1)]
      intentos += 1
      reintento = setTimeout(() => {
        reintento = null
        conectar()
      }, espera)
    }

    // Volver de segundo plano es el momento con más probabilidad de tener la
    // conexión muerta sin saberlo (una tablet suspendida no recibe el cierre
    // hasta que despierta): al volver a mirar, se reintenta ya.
    const alVolver = () => {
      if (!document.hidden && !ws && !reintento) {
        intentos = 0
        conectar()
      }
    }
    document.addEventListener('visibilitychange', alVolver)

    conectar()

    return () => {
      vivo = false
      document.removeEventListener('visibilitychange', alVolver)
      if (reintento) clearTimeout(reintento)
      if (ws) {
        // Se quita `onclose` antes de cerrar: si no, el cierre que provoca
        // este propio desmontaje programaría una reconexión huérfana.
        ws.onclose = null
        ws.close()
      }
    }
  }, [])
}
