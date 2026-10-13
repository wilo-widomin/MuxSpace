// Lo que se decide sin tocar Chrome para la ventana de inicio de sesión.

/**
 * Estado de la conexión con el panel, a partir de lo que contestó `/api/me`.
 *
 * - `ok`: hay sesión.
 * - `login`: el panel responde pero pide entrar (401).
 * - `unreachable`: no hubo respuesta útil. Es lo que se ve mientras falta el
 *   certificado de cliente —Chrome corta el TLS y la pestaña enseña su página
 *   de error, donde no se puede inyectar nada— y también con el panel caído.
 *
 * @param {any} salida - Lo que devolvió el `fetch` inyectado, o `undefined` si
 *   ni siquiera se pudo inyectar.
 * @returns {'ok'|'login'|'unreachable'}
 */
export function sessionState(salida) {
  if (salida && salida.__status === 401) return 'login'
  if (!salida || salida.__error) return 'unreachable'
  return 'ok'
}

/**
 * Posición para centrar una ventana nueva sobre la que el usuario tiene
 * delante. Sin datos de esa ventana, no se propone posición y Chrome elige.
 *
 * @param {{left?: number, top?: number, width?: number, height?: number}|null} parent
 * @param {{width: number, height: number}} size
 * @returns {{left: number, top: number}|null}
 */
export function centeredBounds(parent, size) {
  if (!parent) return null
  const { left, top, width, height } = parent
  if ([left, top, width, height].some((n) => typeof n !== 'number')) return null
  return {
    left: Math.round(left + (width - size.width) / 2),
    top: Math.round(top + (height - size.height) / 2),
  }
}
