// Lo que la extensión guarda entre aperturas. Nada de esto son datos del
// usuario: es la dirección de su panel y a qué grupo de pestañas corresponde
// cada proyecto. La lista de proyectos no se guarda: el popup solo la pinta
// cuando el panel la acaba de dar con la sesión confirmada.

const ORIGIN_KEY = 'panelOrigin'
const GROUPS_KEY = 'projectGroups'

/** @returns {Promise<string>} Origen del panel, o '' si no está configurado. */
export async function readPanelOrigin() {
  const data = await chrome.storage.local.get(ORIGIN_KEY)
  return data[ORIGIN_KEY] || ''
}

/** @param {string} origin */
export async function writePanelOrigin(origin) {
  await chrome.storage.local.set({ [ORIGIN_KEY]: origin })
}

/** @returns {Promise<Record<string, number>>} `id de proyecto -> id de grupo`. */
export async function readProjectGroups() {
  const data = await chrome.storage.local.get(GROUPS_KEY)
  const map = data[GROUPS_KEY]
  return map && typeof map === 'object' ? map : {}
}

/**
 * Anota a qué grupo fue a parar un proyecto.
 *
 * Se guarda el id del grupo y no su título porque el título se puede
 * renombrar —el del proyecto también— y casar por texto perdería el vínculo
 * en cuanto se toca cualquiera de los dos.
 *
 * @param {string} projectId
 * @param {number} groupId
 */
export async function rememberProjectGroup(projectId, groupId) {
  const map = await readProjectGroups()
  map[projectId] = groupId
  await chrome.storage.local.set({ [GROUPS_KEY]: map })
}
