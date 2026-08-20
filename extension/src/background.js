// El service worker: lo único que habla con Chrome y con el panel.
//
// La extensión NUNCA le pide nada al backend por su cuenta. El panel está
// detrás de un certificado de cliente y de una cookie de sesión que
// pertenecen a la pestaña, no a la extensión: quien hace la petición es
// SIEMPRE una pestaña del panel, y la extensión solo lee lo que esa pestaña
// le devuelve. Así no hay que tocar ni el CORS ni la cookie del backend.

import { groupColor, missingUrls, plannedUrls } from './lib/group.js'
import { isPanelUrl, originPattern, panelSpaceUrl } from './lib/panel.js'
import {
  readPanelOrigin,
  readProjectGroups,
  readProjects,
  rememberProjectGroup,
  writeProjects,
} from './lib/storage.js'

/** Error con mensaje ya listo para enseñar en el popup. */
class ExtensionError extends Error {}

/**
 * Función que se ejecuta DENTRO de la pestaña del panel para pedir los
 * proyectos. Se inyecta en el mundo principal (`MAIN`), o sea que la
 * petición sale exactamente igual que si la hiciera el propio panel: con su
 * cookie y su certificado.
 */
function fetchProjectsInPage() {
  return fetch('/api/projects', { credentials: 'same-origin' })
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
 * Pide los proyectos al panel a través de una de sus pestañas.
 *
 * @param {string} origin
 * @returns {Promise<{projects: Array, bridgeTabId: number, opened: boolean}>}
 */
async function loadProjects(origin) {
  const { tabId, opened } = await panelBridge(origin)
  let resultados
  try {
    resultados = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: fetchProjectsInPage,
    })
  } catch (err) {
    throw new ExtensionError(`No se pudo hablar con el panel: ${err.message}`)
  }
  const salida = resultados?.[0]?.result
  if (!salida || salida.__error) {
    // Lo más probable con diferencia: la sesión del panel caducó y la API
    // responde 401. Se dice así y no "error desconocido".
    throw new ExtensionError(
      `El panel no devolvió los proyectos (${salida?.__error || 'sin respuesta'}). ` +
        'Comprueba que has iniciado sesión en el panel.',
    )
  }
  if (!Array.isArray(salida)) {
    throw new ExtensionError('El panel devolvió algo que no es una lista de proyectos.')
  }
  await writeProjects(salida)
  return { projects: salida, bridgeTabId: tabId, opened }
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

  const urlPanel = panelSpaceUrl(origin, project.space)
  const planned = plannedUrls(project, urlPanel)
  const existente = await findExistingGroup(project)

  const abiertasEnGrupo =
    existente === null ? [] : await chrome.tabs.query({ groupId: existente })
  const faltan = missingUrls(
    planned,
    abiertasEnGrupo.map((t) => t.url || t.pendingUrl || ''),
    origin,
  )

  // La pestaña puente, si la abrió la extensión, se convierte en la del panel
  // del grupo en vez de crear otra y dejar una en blanco por ahí.
  const nuevas = []
  let puenteUsado = false
  for (const url of faltan) {
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

  return { groupId, opened: nuevas.length }
}

// El popup no hace nada por su cuenta: pide y enseña el resultado.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const acciones = {
    openProject: () => openProject(message.projectId),
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
