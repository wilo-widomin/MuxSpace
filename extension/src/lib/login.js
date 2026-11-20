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

/**
 * ¿Qué hacer con la puente para enseñar el login o el selector de certificado?
 *
 * - `none`: hay sesión, no hay nada que enseñar.
 * - `replace`: la puente es una ventana de la extensión (nace minimizada).
 *   Se cierra y se abre otra ya visible: nunca se restaura la minimizada,
 *   porque en macOS el selector de certificado que nace con la ventana
 *   minimizada no se pinta al restaurarla.
 * - `open`: la puente es una pestaña del usuario, que no se toca; la ventana
 *   de login se abre aparte.
 *
 * @param {{opened: boolean}} bridge
 * @param {'ok'|'login'|'unreachable'} state
 * @returns {'none'|'replace'|'open'}
 */
export function loginWindowPlan(bridge, state) {
  if (state === 'ok') return 'none'
  return bridge.opened ? 'replace' : 'open'
}

/**
 * ¿Hay que empezar un login o unirse al que ya está en curso?
 *
 * - `start`: no hay ninguno; se crea la puente y, si hace falta, se abre la
 *   ventana de login.
 * - `join`: ya hay una ventana de login abierta (quizá tapada por otra). No se
 *   crea puente auxiliar nueva —quedaría minimizada y huérfana en el dock—:
 *   se pone delante esa ventana y se espera a ese mismo login.
 *
 * @param {boolean} loginInProgress
 * @returns {'start'|'join'}
 */
export function loginAction(loginInProgress) {
  return loginInProgress ? 'join' : 'start'
}

/**
 * Llamadas a `chrome.windows.update` (en orden y por separado) para traer
 * delante una ventana de login que puede estar tapada o minimizada. El estado
 * va aparte del foco: juntos, Chrome puede ignorar uno de los dos.
 *
 * @param {{state?: string}|null} win - La ventana, como la devuelve `windows.get`.
 * @returns {Array<{state?: 'normal', focused?: true, drawAttention?: true}>}
 */
export function loginFocusUpdates(win) {
  const updates = []
  if (win?.state === 'minimized') updates.push({ state: 'normal' })
  updates.push({ focused: true, drawAttention: true })
  return updates
}

/** Tipo del mensaje con el que el service worker avisa de que hay ventana de login. */
export const LOGIN_STARTED = 'loginStarted'

/**
 * ¿Es este mensaje el aviso de que se abrió (o se puso delante) la ventana de
 * login? El popup lo escucha para cerrarse: el login se hace en esa ventana y
 * el popup ya no tiene nada que enseñar.
 *
 * @param {any} message
 * @returns {boolean}
 */
export function isLoginStarted(message) {
  return message?.type === LOGIN_STARTED
}

/**
 * ¿Es esperable el fallo de `chrome.runtime.sendMessage` al avisar al popup?
 * Si el popup ya no existe, Chrome rechaza con «Receiving end does not exist»
 * (o «message port closed»): no es un error, solo que nadie escuchaba.
 *
 * @param {any} err
 * @returns {boolean}
 */
export function isNoReceiverError(err) {
  const texto = String(err?.message ?? err ?? '')
  return /receiving end does not exist|message port closed|message channel closed/i.test(texto)
}
