// Cuándo cuenta el tiempo como trabajo.
//
// La regla que da sentido a todo el registro: **la salida del terminal no es
// actividad**. Cuando el agente construye, el WebSocket del PTY escupe texto
// durante minutos con el usuario en otra pestaña; si esos bytes contaran, se
// medirían exactamente las horas que NO se trabaja y el dato quedaría
// invertido. Por eso este módulo no sabe nada del puente: solo mira entrada
// del usuario y el foco del documento.
//
// Y el foco solo no basta: una pestaña abierta mientras se come apuntaría
// 45 minutos falsos. Hacen falta las dos cosas.

// Tras la última entrada, el reloj sigue corriendo este tiempo. Es el corte
// que evita los 45 minutos falsos, y a la vez la fuente de un sobreconteo de
// hasta 3 minutos por ráfaga de trabajo. Ese sesgo compensa el contrario —leer
// una respuesta larga sin tocar nada no cuenta—, así que bajarlo "para
// afinar" empeora el dato en vez de mejorarlo. Ver docs/muxspace.md.
export const IDLE_TIMEOUT_MS = 3 * 60 * 1000

// Cada cuánto se manda el latido. Coincide con la ranura del servidor: latir
// más rápido solo escribiría en la misma ranura, y más lento dejaría huecos
// que ya no se pueden recuperar.
export const HEARTBEAT_MS = 30 * 1000

// Duración máxima del modo manual sin ninguna entrada real. El interruptor
// existe para cuando el usuario SÍ trabaja y el detector no lo ve (leer un
// rato largo, dictar, mirar una pantalla). Pero un interruptor sin límite es
// el tramo abierto que este diseño evita: si se queda encendido y el usuario
// se va, apuntaría la noche entera.
export const MANUAL_MAX_MS = 30 * 60 * 1000

export const ACTIVITY_EVENTS = ['keydown', 'mousemove', 'click', 'scroll', 'touchstart']

/**
 * Decide si esta ranura cuenta como trabajada.
 *
 * @param {object} estado
 * @param {boolean} estado.hasFocus - El documento tiene el foco.
 * @param {number} estado.lastInput - Instante de la última entrada del usuario.
 * @param {boolean} estado.manual - El cronómetro está forzado a mano.
 * @param {number} estado.manualSince - Cuándo se forzó.
 * @param {number} ahora
 * @returns {boolean}
 */
export function isWorking({ hasFocus, lastInput, manual, manualSince }, ahora) {
  if (!hasFocus) return false
  if (ahora - lastInput < IDLE_TIMEOUT_MS) return true
  // Modo manual: cuenta aunque no haya entrada, pero caduca solo.
  return Boolean(manual) && ahora - manualSince < MANUAL_MAX_MS
}

/** ¿El modo manual ya caducó? (para poder apagar el indicador). */
export function manualExpired({ manual, manualSince }, ahora) {
  return Boolean(manual) && ahora - manualSince >= MANUAL_MAX_MS
}

/** Segundos -> "3 h 25 min" / "48 min" / "—". Para la vista de tiempos. */
export function formatDuration(segundos) {
  if (!segundos) return '—'
  const horas = Math.floor(segundos / 3600)
  const minutos = Math.round((segundos % 3600) / 60)
  if (!horas) return `${minutos} min`
  // 90 minutos redondeados a 60 darían "2 h 60 min".
  if (minutos === 60) return `${horas + 1} h`
  return minutos ? `${horas} h ${minutos} min` : `${horas} h`
}
