// Lo que la extensión sabe del panel: dónde vive y cómo se le pide un
// espacio. La dirección NO está escrita aquí — la escribe el usuario en la
// página de opciones — porque es su red y no tiene nada que hacer en un
// repositorio.

/**
 * Normaliza lo que el usuario escribe en opciones a un origen utilizable.
 *
 * Se acepta escribir solo el host («panel.interno», «192.168.1.10:8443»)
 * porque es lo que uno teclea; sin esquema se asume https, que es como está
 * publicado el panel. Devuelve el ORIGEN, sin ruta ni barra final: todo lo
 * que se construye después cuelga de ahí.
 *
 * @param {string} raw - Lo tecleado en el formulario de opciones.
 * @returns {string} Origen normalizado, o '' si no hay nada utilizable.
 */
export function normalizePanelOrigin(raw) {
  const text = String(raw ?? '').trim()
  if (!text) return ''
  const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(text)
    ? text
    : `https://${text}`
  let parsed
  try {
    parsed = new URL(withScheme)
  } catch {
    return ''
  }
  // Solo http(s): un `file:` o un `chrome:` aquí no abre ningún panel y sí
  // haría que la extensión pidiera permisos sobre algo que no toca.
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return ''
  if (!parsed.hostname) return ''
  return parsed.origin
}

/**
 * URL del panel abierta en un espacio concreto.
 *
 * `?space=<id>` es una ORDEN DE APERTURA que el panel obedece una vez y
 * luego borra de la barra de direcciones (ver `frontend/src/spaces.js`).
 * Sin espacio se abre el panel a secas, que es lo que corresponde a un
 * proyecto al que le han borrado el suyo.
 *
 * @param {string} origin - Origen normalizado del panel.
 * @param {string|null} spaceId - Id del espacio, o null.
 * @returns {string}
 */
export function panelSpaceUrl(origin, spaceId) {
  if (!spaceId) return `${origin}/`
  return `${origin}/?space=${encodeURIComponent(spaceId)}`
}

/**
 * Patrón de permisos para el origen del panel.
 *
 * @param {string} origin
 * @returns {string}
 */
export function originPattern(origin) {
  return `${origin}/*`
}

/**
 * ¿Esta URL es una pestaña del panel?
 *
 * @param {string} url
 * @param {string} origin
 * @returns {boolean}
 */
export function isPanelUrl(url, origin) {
  if (!url || !origin) return false
  try {
    return new URL(url).origin === origin
  } catch {
    return false
  }
}
