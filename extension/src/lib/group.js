// Qué pestañas tiene que tener el grupo de un proyecto, y cuáles faltan.
//
// Todo lo de este archivo es cálculo puro sobre datos: no habla con Chrome.
// Es la parte que se puede probar sin navegador, y por eso vive aparte de
// `background.js`.

/** Colores que admite `chrome.tabGroups`. */
const GROUP_COLORS = [
  'blue',
  'cyan',
  'green',
  'grey',
  'orange',
  'pink',
  'purple',
  'red',
  'yellow',
]

/**
 * Color estable para un proyecto.
 *
 * Estable y no aleatorio a propósito: el color es la señal con la que uno
 * reconoce su grupo de un vistazo, y si cambiara en cada apertura no serviría
 * para nada. Sale del id, que no cambia aunque se renombre el proyecto.
 *
 * @param {string} projectId
 * @returns {string}
 */
export function groupColor(projectId) {
  const text = String(projectId ?? '')
  let sum = 0
  for (let i = 0; i < text.length; i += 1) sum += text.charCodeAt(i)
  return GROUP_COLORS[sum % GROUP_COLORS.length]
}

/**
 * Las URLs que le tocan al grupo de un proyecto, en orden.
 *
 * **El panel va primero**, a la izquierda del todo: es la pestaña desde la
 * que se trabaja, y las demás son referencia. Detrás, los enlaces en el orden
 * en que el usuario los escribió.
 *
 * @param {{space: string|null, links: Array<{url: string}>}} project
 * @param {string} panelUrl - Panel ya apuntado al espacio del proyecto.
 * @returns {string[]}
 */
export function plannedUrls(project, panelUrl) {
  const links = Array.isArray(project?.links) ? project.links : []
  const urls = links.map((l) => String(l?.url ?? '').trim()).filter(Boolean)
  return [panelUrl, ...urls]
}

/**
 * Compara dos URLs como lo haría una persona: sin distinguir barra final.
 *
 * Sin esto, `https://github.com/foo` y `https://github.com/foo/` serían dos
 * pestañas distintas y el grupo se llenaría de duplicados a la segunda
 * apertura.
 *
 * @param {string} url
 * @returns {string}
 */
export function sameTabKey(url) {
  try {
    const parsed = new URL(url)
    const path = parsed.pathname.endsWith('/')
      ? parsed.pathname.slice(0, -1)
      : parsed.pathname
    return `${parsed.origin}${path}${parsed.search}`
  } catch {
    return String(url ?? '').trim()
  }
}

/**
 * Qué falta por abrir en un grupo que ya existe.
 *
 * Reabrir un proyecto NO reordena ni cierra nada de lo que el usuario tenga
 * en su grupo: solo añade lo que no está. Cerrar una pestaña que él abrió a
 * mano sería perderle trabajo, y reordenar, moverle el sitio.
 *
 * La pestaña del panel es la excepción que NO se compara con `?space=`: si ya
 * hay una pestaña del panel en el grupo, vale, aunque mire otro espacio. Si
 * no, se abriría una segunda cada vez que se cambia de espacio a mano.
 *
 * @param {string[]} planned - Lo que le toca al grupo (ver `plannedUrls`).
 * @param {string[]} existing - URLs de las pestañas que ya tiene.
 * @param {string} panelOrigin - Origen del panel, para reconocer su pestaña.
 * @returns {string[]} Las que hay que abrir, en orden.
 */
export function missingUrls(planned, existing, panelOrigin) {
  const abiertas = new Set(existing.map(sameTabKey))
  const hayPanel = existing.some((url) => {
    try {
      return new URL(url).origin === panelOrigin
    } catch {
      return false
    }
  })
  return planned.filter((url) => {
    let esPanel = false
    try {
      esPanel = new URL(url).origin === panelOrigin
    } catch {
      esPanel = false
    }
    if (esPanel) return !hayPanel
    return !abiertas.has(sameTabKey(url))
  })
}
