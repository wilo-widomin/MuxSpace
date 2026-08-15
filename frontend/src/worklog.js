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

// Duración del modo declarado sin renovarse. El interruptor existe para el
// caso que el detector no puede ver: trabajar en el proyecto FUERA del panel
// —probar la app que estás construyendo en otra pestaña, leer un documento—,
// donde no hay foco ni entrada que medir.
//
// Es renovable, no indefinido: cualquier entrada tuya en el panel o volver a
// su pestaña reinicia la cuenta. Pero si pasan 30 minutos sin que aparezcas,
// se apaga solo. Un interruptor sin caducidad es el tramo abierto que todo
// este diseño evita: se queda encendido, te vas, y apunta la noche entera.
export const MANUAL_MAX_MS = 30 * 60 * 1000

export const ACTIVITY_EVENTS = ['keydown', 'mousemove', 'click', 'scroll', 'touchstart']

/**
 * Decide si esta ranura cuenta como trabajada, y cómo se supo.
 *
 * Dos caminos, y la diferencia entre ellos es lo que después se puede mirar
 * por separado en la vista de tiempos:
 *
 * - **medido** (`auto`): el panel tiene el foco y hubo entrada reciente.
 * - **declarado** (`manual`): el usuario encendió el cronómetro porque está
 *   trabajando en el proyecto FUERA del panel. Aquí no se exige foco —sería
 *   exigir que esté donde precisamente no está—, así que lo que acota el
 *   riesgo es la caducidad y, si el navegador la ofrece, saber si sigue
 *   delante del ordenador.
 *
 * @param {object} estado
 * @param {boolean} estado.hasFocus - El documento tiene el foco.
 * @param {number} estado.lastInput - Instante de la última entrada del usuario.
 * @param {boolean} estado.manual - El cronómetro está encendido a mano.
 * @param {number} estado.manualSince - Última renovación del modo declarado.
 * @param {boolean} [estado.userAway] - El sistema dice que no estás delante
 *   (pantalla bloqueada o sin actividad). Solo lo sabemos en navegadores con
 *   detección de inactividad y con permiso; si no, llega `undefined`.
 * @param {number} ahora
 * @returns {'auto'|'manual'|null} cómo cuenta, o null si no cuenta
 */
export function isWorking(
  { hasFocus, lastInput, manual, manualSince, userAway },
  ahora,
) {
  if (hasFocus && ahora - lastInput < IDLE_TIMEOUT_MS) return 'auto'
  if (!manual) return null
  // Encendido pero caducado, o el sistema dice que no hay nadie: no cuenta.
  if (ahora - manualSince >= MANUAL_MAX_MS) return null
  if (userAway) return null
  return 'manual'
}

/** ¿El modo declarado ya caducó? (para poder apagarlo y avisar). */
export function manualExpired({ manual, manualSince }, ahora) {
  return Boolean(manual) && ahora - manualSince >= MANUAL_MAX_MS
}

/**
 * Fecha en dd/mm/aaaa, siempre, sea cual sea el idioma del navegador.
 *
 * `toLocaleDateString()` cambia de formato con el idioma (en inglés sale
 * mm/dd), y una tabla donde 03/04 significa una cosa u otra según quién la
 * mire no es una tabla de fechas.
 *
 * @param {string|number|Date} valor - 'aaaa-mm-dd', epoch en SEGUNDOS o Date.
 */
export function formatDate(valor) {
  if (typeof valor === 'string') {
    // Los días del servidor ya vienen calculados en hora local: se reordenan
    // sin pasar por Date, que interpretaría la cadena como UTC y podría
    // restar un día.
    const [anio, mes, dia] = valor.split('-')
    return `${dia}/${mes}/${anio}`
  }
  const fecha = valor instanceof Date ? valor : new Date(valor * 1000)
  const dia = String(fecha.getDate()).padStart(2, '0')
  const mes = String(fecha.getMonth() + 1).padStart(2, '0')
  return `${dia}/${mes}/${fecha.getFullYear()}`
}

/**
 * Hora local en 24 h. Con `segundos`, hh:mm:ss.
 *
 * Los tramos se listan CON segundos a propósito: las ranuras duran 30 s, así
 * que un tramo puede acabar a las 16:11:00 y el siguiente empezar a las
 * 16:11:00 —contiguos, no solapados—, y a resolución de minuto los dos se
 * pintan «16:11» y parecen pisarse.
 */
export function formatTime(epochSegundos, { segundos = false } = {}) {
  const fecha = new Date(epochSegundos * 1000)
  const dosCifras = (n) => String(n).padStart(2, '0')
  const base = `${dosCifras(fecha.getHours())}:${dosCifras(fecha.getMinutes())}`
  return segundos ? `${base}:${dosCifras(fecha.getSeconds())}` : base
}

/**
 * Duración SIN redondear a minutos: "45 s", "1 min 30 s", "3 h 25 min".
 *
 * Se usa donde se listan tramos sueltos. Con el redondeo a minutos, once
 * tramos de 30 s se pintaban como "1 min" cada uno y la lista parecía sumar
 * 15 minutos cuando el total real eran 11: cada fila mentía un poco y el
 * error se acumulaba a la vista.
 */
export function formatDurationExact(segundos) {
  if (!segundos) return '—'
  const horas = Math.floor(segundos / 3600)
  const minutos = Math.floor((segundos % 3600) / 60)
  const resto = segundos % 60
  if (horas) return minutos ? `${horas} h ${minutos} min` : `${horas} h`
  if (minutos) return resto ? `${minutos} min ${resto} s` : `${minutos} min`
  return `${resto} s`
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
