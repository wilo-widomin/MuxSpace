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
 * Qué hacer con un grupo que ya existe para dejarlo como toca.
 *
 * Reabrir un proyecto NO cierra ni reordena nada de lo que el usuario tenga
 * puesto ahí: cerrarle una pestaña sería perderle trabajo, y reordenarlas,
 * moverle el sitio. Solo se añade lo que falta.
 *
 * La pestaña del panel es la excepción, y por eso este cálculo devuelve dos
 * cosas en vez de una lista: si el grupo ya tiene una pestaña del panel
 * mirando otro espacio —o ninguno, como las que quedaron de antes de que los
 * proyectos tuvieran espacio—, se la **lleva** al del proyecto en vez de
 * abrir una segunda al lado. Abrir el proyecto es ir a su sitio, y dos
 * paneles en el mismo grupo no son dos cosas distintas: son un duplicado.
 *
 * @param {string[]} planned - Lo que le toca al grupo; el panel es el primero.
 * @param {Array<{id: number, url: string}>} existing - Pestañas que ya tiene.
 * @param {string} panelOrigin - Origen del panel, para reconocer su pestaña.
 * @returns {{navigate: {tabId: number, url: string}|null, open: string[]}}
 */
export function reconcileGroup(planned, existing, panelOrigin) {
  const [panelUrl, ...links] = planned
  const abiertas = Array.isArray(existing) ? existing : []

  const esDelPanel = (url) => {
    try {
      return new URL(url).origin === panelOrigin
    } catch {
      return false
    }
  }

  const pestanaPanel = abiertas.find((t) => esDelPanel(t?.url || ''))
  const navigate =
    pestanaPanel && sameTabKey(pestanaPanel.url) !== sameTabKey(panelUrl)
      ? { tabId: pestanaPanel.id, url: panelUrl }
      : null

  const yaAbiertas = new Set(abiertas.map((t) => sameTabKey(t?.url || '')))
  const open = []
  if (!pestanaPanel) open.push(panelUrl)
  for (const link of links) {
    if (!yaAbiertas.has(sameTabKey(link))) open.push(link)
  }
  return { navigate, open }
}
