// El service worker: lo único que habla con Chrome y con el panel.
//
// La extensión NUNCA le pide nada al backend por su cuenta. El panel está
// detrás de un certificado de cliente y de una cookie de sesión que
// pertenecen a la pestaña, no a la extensión: quien hace la petición es
// SIEMPRE una pestaña del panel, y la extensión solo lee lo que esa pestaña
// le devuelve. Así no hay que tocar ni el CORS ni la cookie del backend.

import { groupColor, plannedUrls, reconcileGroup } from './lib/group.js'
import { isPanelUrl, originPattern, panelSpaceUrl } from './lib/panel.js'
import { needsLaunch, sessionsToAdopt } from './lib/sessions.js'
import {
  readPanelOrigin,
  readProjectGroups,
  readProjects,
  rememberProjectGroup,
  writeProjects,
} from './lib/storage.js'

/** Error con mensaje ya listo para enseñar en el popup. */
class ExtensionError extends Error {}

// Las dos funciones siguientes se ejecutan DENTRO de la pestaña del panel,
// inyectadas en su mundo principal (`MAIN`): las peticiones salen exactamente
// igual que si las hiciera el propio panel, con su cookie y su certificado.
//
// No pueden importar nada ni cerrar sobre variables de aquí —se serializan
// para inyectarlas—, así que son deliberadamente tontas: piden una ruta y
// devuelven lo que venga. Quién decide qué pedir es `openProject`.

/** GET a una ruta de la API del panel. */
function getInPage(path) {
  return fetch(path, { credentials: 'same-origin' })
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}` }))
    .catch((e) => ({ __error: String(e) }))
}

/**
 * Espacio que está mirando esta pestaña del panel.
 *
 * Hace falta preguntárselo porque el panel **borra el `?space=` de la URL** en
 * cuanto lo obedece (es una orden de apertura, no el estado de la pestaña;
 * ver `frontend/src/App.jsx`). Mirando solo la URL, una pestaña que ya está
 * en el espacio correcto parece estar en otro, y se la recargaría en cada
 * apertura del proyecto tirándole al usuario lo que estuviera haciendo.
 */
function readActiveSpaceInPage() {
  try {
    return { space: sessionStorage.getItem('muxspace:active-space') }
  } catch (e) {
    return { __error: String(e) }
  }
}

/** POST sin cuerpo a una ruta de la API del panel. */
function postInPage(path) {
  return fetch(path, { method: 'POST', credentials: 'same-origin' })
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}` }))
    .catch((e) => ({ __error: String(e) }))
}

/** PUT con cuerpo JSON a una ruta de la API del panel. */
function putInPage(path, body) {
  return fetch(path, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}` }))
    .catch((e) => ({ __error: String(e) }))
}

/** Espera a que una pestaña termine de cargar. */
function waitForLoad(tabId) {
  return new Promise((resolve) => {
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener)
        resolve()
      }
    }
    chrome.tabs.onUpdated.addListener(listener)
  })
}

/**
 * Una pestaña del panel con la que hablar, y si hubo que abrirla, cuál es.
 *
 * Se reutiliza la que ya haya SIN TOCARLA: navegar la pestaña de alguien
 * para preguntarle algo le tiraría lo que estuviera mirando.
 *
 * @param {string} origin
 * @returns {Promise<{tabId: number, opened: boolean}>}
 */
async function panelBridge(origin) {
  const abiertas = await chrome.tabs.query({ url: originPattern(origin) })
  if (abiertas.length > 0) return { tabId: abiertas[0].id, opened: false }

  const creada = await chrome.tabs.create({ url: `${origin}/`, active: false })
  await waitForLoad(creada.id)
  return { tabId: creada.id, opened: true }
}

/**
 * Ejecuta una petición a la API desde una pestaña del panel.
 *
 * @param {number} tabId - Pestaña del panel que hace de puente.
 * @param {Function} func - `getInPage` o `postInPage`.
 * @param {string} path - Ruta de la API.
 * @returns {Promise<any>} Lo que devuelva la API.
 */
async function askPanel(tabId, func, path, body) {
  let resultados
  try {
    resultados = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func,
      args: body === undefined ? [path] : [path, body],
    })
  } catch (err) {
    throw new ExtensionError(`No se pudo hablar con el panel: ${err.message}`)
  }
  const salida = resultados?.[0]?.result
  if (!salida || salida.__error) {
    // Lo más probable con diferencia: la sesión del panel caducó y la API
    // responde 401. Se dice así y no "error desconocido".
    throw new ExtensionError(
      `El panel no respondió a ${path} (${salida?.__error || 'sin respuesta'}). ` +
        'Comprueba que has iniciado sesión en el panel.',
    )
  }
  return salida
}

/**
 * Pide los proyectos al panel a través de una de sus pestañas.
 *
 * @param {string} origin
 * @returns {Promise<{projects: Array, bridgeTabId: number, opened: boolean}>}
 */
async function loadProjects(origin) {
  const { tabId, opened } = await panelBridge(origin)
  const salida = await askPanel(tabId, getInPage, '/api/projects')
  if (!Array.isArray(salida)) {
    throw new ExtensionError('El panel devolvió algo que no es una lista de proyectos.')
  }
  await writeProjects(salida)
  return { projects: salida, bridgeTabId: tabId, opened }
}

/**
 * Deja el espacio del proyecto con sus terminales dentro.
 *
 * Son dos cosas, y las dos hacen falta para que abrir el proyecto no lleve a
 * un espacio vacío:
 *
 *  1. **Traer las suyas que estén fuera.** Las lanzadas antes de que el
 *     proyecto tuviera espacio se quedaron en «Sin asignar», y ahí nadie las
 *     ve al abrir el proyecto.
 *  2. **Lanzarlo si no tiene ninguna.** El panel enseña por sí solo cualquier
 *     sesión de su espacio, así que con que exista, aparece.
 *
 * Nada de esto aborta la apertura del grupo: si falla, se devuelve el aviso y
 * las pestañas se abren igual.
 *
 * @param {number} tabId - Pestaña puente.
 * @param {{id: string, space: string|null}} project
 * @returns {Promise<string|null>} Aviso para el usuario, o null si todo fue bien.
 */
async function ensureProjectReady(tabId, project) {
  const sesiones = await askPanel(tabId, getInPage, '/api/sessions')

  for (const nombre of sessionsToAdopt(sesiones, project.id, project.space)) {
    const ruta = `/api/sessions/${encodeURIComponent(nombre)}/space`
    try {
      await askPanel(tabId, putInPage, ruta, { space: project.space })
    } catch (err) {
      return `El grupo se abrió, pero «${nombre}» no se pudo mover a su espacio: ${err.message}`
    }
  }

  if (!needsLaunch(sesiones, project.id)) return null

  const ruta = `/api/projects/${encodeURIComponent(project.id)}/run`
  try {
    await askPanel(tabId, postInPage, ruta)
    return null
  } catch (err) {
    return `El grupo se abrió, pero no se pudo lanzar la terminal: ${err.message}`
  }
}

/**
 * URL que representa lo que una pestaña del grupo está enseñando de verdad.
 *
 * Para las del panel es la de su espacio actual, no la que se ve en la barra
 * de direcciones. Para el resto, la suya. Si la pestaña no contesta, se usa
 * su URL: el peor caso es una recarga de más, no un fallo.
 *
 * @param {{id: number, url?: string, pendingUrl?: string}} tab
 * @param {string} origin
 * @returns {Promise<{id: number, url: string}>}
 */
async function effectiveTabUrl(tab, origin) {
  const url = tab.url || tab.pendingUrl || ''
  if (!isPanelUrl(url, origin)) return { id: tab.id, url }
  try {
    const resultados = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: readActiveSpaceInPage,
    })
    const salida = resultados?.[0]?.result
    if (!salida || salida.__error) return { id: tab.id, url }
    // `unassigned` no es un espacio: es no tener ninguno (ver `spaces.js`).
    const space = salida.space && salida.space !== 'unassigned' ? salida.space : null
    return { id: tab.id, url: panelSpaceUrl(origin, space) }
  } catch {
    return { id: tab.id, url }
  }
}

/**
 * El grupo que ya tiene este proyecto, si sigue vivo.
 *
 * Se busca primero por el id guardado y luego por el título, porque el
 * primero se pierde al reinstalar la extensión y el segundo es lo que el
 * usuario ve.
 *
 * @param {{id: string, title: string}} project
 * @returns {Promise<number|null>}
 */
async function findExistingGroup(project) {
  const mapa = await readProjectGroups()
  const guardado = mapa[project.id]
  if (typeof guardado === 'number') {
    try {
      await chrome.tabGroups.get(guardado)
      return guardado
    } catch {
      // El grupo se cerró. Se sigue por título.
    }
  }
  const porTitulo = await chrome.tabGroups.query({ title: project.title })
  return porTitulo.length > 0 ? porTitulo[0].id : null
}

/**
 * Abre (o recupera) el grupo de pestañas de un proyecto.
 *
 * @param {string} projectId
 * @returns {Promise<{groupId: number, opened: number}>}
 */
async function openProject(projectId) {
  const origin = await readPanelOrigin()
  if (!origin) {
    throw new ExtensionError('Falta la dirección del panel: ábrela en las opciones.')
  }

  const { projects, bridgeTabId, opened } = await loadProjects(origin)
  const project = projects.find((p) => p.id === projectId)
  if (!project) {
    throw new ExtensionError('Ese proyecto ya no existe en el panel.')
  }

  // Antes de tocar la pestaña puente: si es la que la extensión abrió, luego
  // se la lleva el grupo y ya no serviría para preguntar.
  const avisos = []
  const avisoTerminal = await ensureProjectReady(bridgeTabId, project)
  if (avisoTerminal) avisos.push(avisoTerminal)
  // Los proyectos creados antes de que existiera el campo no tienen espacio,
  // y entonces el panel se abre donde le toque en vez de en el del proyecto.
  // Callárselo hace parecer que la extensión no funciona.
  if (!project.space) {
    avisos.push(
      `«${project.title}» no tiene espacio asignado, así que el panel se abre ` +
        'sin espacio. Asígnaselo editando el proyecto en el panel.',
    )
  }

  const urlPanel = panelSpaceUrl(origin, project.space)
  const planned = plannedUrls(project, urlPanel)
  const existente = await findExistingGroup(project)

  const abiertasEnGrupo =
    existente === null ? [] : await chrome.tabs.query({ groupId: existente })
  const { navigate, open } = reconcileGroup(
    planned,
    await Promise.all(abiertasEnGrupo.map((t) => effectiveTabUrl(t, origin))),
    origin,
  )

  // La pestaña del panel que ya estaba en el grupo se lleva al espacio del
  // proyecto. Es lo que arregla los grupos creados cuando los proyectos no
  // tenían espacio, y lo que evita dos paneles en el mismo grupo.
  if (navigate) {
    await chrome.tabs.update(navigate.tabId, { url: navigate.url })
  }

  // La pestaña puente, si la abrió la extensión, se convierte en la del panel
  // del grupo en vez de crear otra y dejar una en blanco por ahí.
  const nuevas = []
  let puenteUsado = false
  for (const url of open) {
    if (opened && !puenteUsado && isPanelUrl(url, origin)) {
      await chrome.tabs.update(bridgeTabId, { url })
      nuevas.push(bridgeTabId)
      puenteUsado = true
      continue
    }
    const creada = await chrome.tabs.create({ url, active: false })
    nuevas.push(creada.id)
  }

  // La puente que no se aprovechó sobra: se abrió solo para preguntar.
  if (opened && !puenteUsado) {
    await chrome.tabs.remove(bridgeTabId)
  }

  let groupId = existente
  if (nuevas.length > 0) {
    groupId =
      existente === null
        ? await chrome.tabs.group({ tabIds: nuevas })
        : await chrome.tabs.group({ groupId: existente, tabIds: nuevas })
  }
  if (groupId === null) {
    throw new ExtensionError('No había nada que abrir ni ningún grupo al que ir.')
  }

  await chrome.tabGroups.update(groupId, {
    title: project.title,
    color: groupColor(project.id),
    collapsed: false,
  })
  await rememberProjectGroup(project.id, groupId)

  // Poner delante la primera pestaña del grupo, que es la del panel.
  const delGrupo = await chrome.tabs.query({ groupId })
  if (delGrupo.length > 0) {
    const primera = delGrupo.reduce((a, b) => (a.index <= b.index ? a : b))
    await chrome.tabs.update(primera.id, { active: true })
    await chrome.windows.update(primera.windowId, { focused: true })
  }

  return { groupId, opened: nuevas.length, warning: avisos.join(' ') || null }
}

// Aperturas en curso, por proyecto.
//
// Abrir un proyecto son varias esperas seguidas (preguntar al panel, lanzar
// la terminal, crear pestañas). Sin esto, un doble clic en el popup arranca
// dos aperturas que ven las dos el mismo "no hay grupo" y crean dos grupos
// iguales. La segunda se engancha a la primera en vez de competir con ella.
const enCurso = new Map()

function openProjectOnce(projectId) {
  const yaVa = enCurso.get(projectId)
  if (yaVa) return yaVa
  const promesa = openProject(projectId).finally(() => enCurso.delete(projectId))
  enCurso.set(projectId, promesa)
  return promesa
}

// El popup no hace nada por su cuenta: pide y enseña el resultado.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const acciones = {
    openProject: () => openProjectOnce(message.projectId),
    refreshProjects: async () => {
      const origin = await readPanelOrigin()
      if (!origin) {
        throw new ExtensionError('Falta la dirección del panel: ábrela en las opciones.')
      }
      const { projects, bridgeTabId, opened } = await loadProjects(origin)
      if (opened) await chrome.tabs.remove(bridgeTabId)
      return { projects }
    },
    cachedProjects: async () => ({ projects: await readProjects() }),
  }
  const accion = acciones[message?.type]
  if (!accion) return false

  accion()
    .then((data) => sendResponse({ ok: true, ...data }))
    .catch((err) => sendResponse({ ok: false, error: err.message }))
  // `true`: la respuesta llega más tarde, en la promesa.
  return true
})
