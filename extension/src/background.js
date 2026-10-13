// El service worker: lo único que habla con Chrome y con el panel.
//
// La extensión NUNCA le pide nada al backend por su cuenta. El panel está
// detrás de un certificado de cliente y de una cookie de sesión que
// pertenecen a la pestaña, no a la extensión: quien hace la petición es
// SIEMPRE una pestaña del panel, y la extensión solo lee lo que esa pestaña
// le devuelve. Así no hay que tocar ni el CORS ni la cookie del backend.

import { groupColor, plannedUrls, reconcileGroup } from './lib/group.js'
import { centeredBounds, sessionState } from './lib/login.js'
import { isAuthError, isPanelUrl, originPattern, panelSpaceUrl } from './lib/panel.js'
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

/**
 * No hay sesión en el panel.
 *
 * Es el único error que tiene arreglo sin salir de la extensión: basta con
 * enseñarle al usuario la pantalla de login del panel. Por eso viaja como
 * clase propia y el popup la distingue para ofrecer el botón de entrar.
 */
class AuthError extends ExtensionError {
  constructor(message = 'No hay sesión en el panel: entra para poder abrir proyectos.') {
    super(message)
  }
}

// Cada cuánto se le pregunta al panel si ya hay sesión, y cuánto se espera
// antes de rendirse. El sondeo también mantiene despierto al service worker.
const LOGIN_POLL_MS = 1500
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000

// Lo que se espera a que recargue la pestaña del usuario tras el login.
const LOAD_TIMEOUT_MS = 6000

// Lo que se espera a que una pestaña conteste a `/api/me`.
const PROBE_TIMEOUT_MS = 3000

// Paciencia con la puente minimizada recién abierta. Con sesión y certificado
// ya elegido, `/api/me` contesta en unos cientos de milisegundos; mientras
// falta el certificado no contesta nada, y la única forma de saberlo es que
// pase este rato en silencio. Se pregunta cada `BRIDGE_POLL_MS`.
const BRIDGE_PATIENCE_MS = 1500
const BRIDGE_POLL_MS = 200
// Tras el login, la puente nueva ya tiene certificado: solo falta que cargue.
const RENEWED_PATIENCE_MS = 6000

// Tamaño de la ventana de inicio de sesión: lo justo para el login del panel.
const LOGIN_WINDOW = { width: 480, height: 720 }

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
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}`, __status: r.status }))
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
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}`, __status: r.status }))
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
    .then((r) => (r.ok ? r.json() : { __error: `HTTP ${r.status}`, __status: r.status }))
    .catch((e) => ({ __error: String(e) }))
}

/**
 * Espera a que una pestaña termine de cargar, como mucho `timeoutMs`.
 *
 * Con tope porque una pestaña puede no terminar nunca: la de segundo plano
 * que espera a que se elija el certificado de cliente se queda así.
 *
 * @returns {Promise<boolean>} Si terminó de cargar a tiempo.
 */
function waitForLoad(tabId, timeoutMs = LOAD_TIMEOUT_MS) {
  return new Promise((resolve) => {
    const terminar = (cargada) => {
      clearTimeout(reloj)
      chrome.tabs.onUpdated.removeListener(listener)
      resolve(cargada)
    }
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') terminar(true)
    }
    const reloj = setTimeout(() => terminar(false), timeoutMs)
    chrome.tabs.onUpdated.addListener(listener)
  })
}

/**
 * Una pestaña del panel con la que hablar, y si hubo que abrirla, cuál es.
 *
 * Se reutiliza la que ya haya SIN TOCARLA: navegar la pestaña de alguien
 * para preguntarle algo le tiraría lo que estuviera mirando.
 *
 * Si no hay ninguna, se abre en una **ventana emergente minimizada**, nunca
 * como pestaña de la ventana del usuario: si falta el certificado de cliente,
 * Chrome trae al frente la pestaña que lo pide, y en la ventana del usuario
 * eso tapaba a la de login. Así, si hace falta entrar, esa misma ventana se
 * pone delante y hace de ventana de login (`loginInWindow`).
 *
 * @param {string} origin
 * @returns {Promise<{tabId: number, opened: boolean, windowId?: number}>}
 */
async function panelBridge(origin) {
  const abiertas = await chrome.tabs.query({ url: originPattern(origin), windowType: 'normal' })
  if (abiertas.length > 0) return { tabId: abiertas[0].id, opened: false }

  const ventana = await chrome.windows.create({
    url: `${origin}/`,
    type: 'popup',
    state: 'minimized',
  })
  return { tabId: ventana.tabs[0].id, opened: true, windowId: ventana.id }
}

/** Cierra la puente si la abrió la extensión. La del usuario no se toca. */
async function closeBridge(bridge) {
  if (bridge.opened) await chrome.windows.remove(bridge.windowId).catch(() => {})
}

/**
 * Ejecuta una petición a la API desde una pestaña del panel, sin juzgarla.
 *
 * Devuelve tal cual lo que salga, incluidos los `{__error, __status}`: quien
 * llama decide si un 401 es un fallo o una invitación a pedir el login.
 *
 * @param {number} tabId - Pestaña del panel que hace de puente.
 * @param {Function} func - `getInPage`, `postInPage` o `putInPage`.
 * @param {string} path - Ruta de la API.
 * @param {any} [body] - Cuerpo, para el PUT.
 * @returns {Promise<any>}
 */
async function tryPanel(tabId, func, path, body) {
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
  return resultados?.[0]?.result
}

/**
 * Lo mismo, pero exigiendo respuesta buena: cualquier error aborta.
 *
 * @returns {Promise<any>} Lo que devuelva la API.
 */
async function askPanel(tabId, func, path, body) {
  const salida = await tryPanel(tabId, func, path, body)
  if (isAuthError(salida)) throw new AuthError()
  if (!salida || salida.__error) {
    throw new ExtensionError(
      `El panel no respondió a ${path} (${salida?.__error || 'sin respuesta'}).`,
    )
  }
  return salida
}

/**
 * ¿Cómo está la conexión con el panel desde esta pestaña?
 *
 * `GET /api/me` es la pregunta barata: contesta 401 si no hay sesión y no
 * toca nada si la hay. Que ni siquiera se pueda inyectar —la pestaña enseña
 * la página de error de Chrome porque falta el certificado, o aún no ha
 * cargado— no es un fallo aquí: es otra forma de «todavía no».
 *
 * @param {number} tabId
 * @returns {Promise<'ok'|'login'|'unreachable'>}
 */
async function probeSession(tabId, timeoutMs = PROBE_TIMEOUT_MS) {
  // Con tope y sin esperar a la carga: mientras Chrome espera a que se elija
  // el certificado, la página no termina de cargar nunca, y una inyección
  // normal (que aguarda a `document_idle`) se quedaría colgada para siempre.
  const inyeccion = chrome.scripting
    .executeScript({
      target: { tabId },
      world: 'MAIN',
      injectImmediately: true,
      func: getInPage,
      args: ['/api/me'],
    })
    .then((resultados) => sessionState(resultados?.[0]?.result))
    .catch(() => 'unreachable')
  const tope = new Promise((resolve) => setTimeout(() => resolve('unreachable'), timeoutMs))
  return Promise.race([inyeccion, tope])
}

/**
 * Pregunta seguido a una puente recién abierta hasta tener respuesta clara.
 *
 * La pestaña del usuario ya está cargada y basta con una pregunta; la puente
 * que acaba de abrir la extensión puede no tener aún documento donde
 * inyectar, así que se reintenta cada `BRIDGE_POLL_MS` hasta `patienceMs`.
 *
 * @param {{tabId: number, opened: boolean}} bridge
 * @param {number} patienceMs
 * @returns {Promise<'ok'|'login'|'unreachable'>}
 */
async function waitForSession(bridge, patienceMs) {
  if (!bridge.opened) return probeSession(bridge.tabId)
  const limite = Date.now() + patienceMs
  for (;;) {
    const restante = limite - Date.now()
    if (restante <= 0) return 'unreachable'
    const estado = await probeSession(bridge.tabId, Math.min(restante, 500))
    if (estado !== 'unreachable') return estado
    await new Promise((resolve) => setTimeout(resolve, BRIDGE_POLL_MS))
  }
}

/** La última ventana normal que tuvo el foco, o null. */
async function frontWindow() {
  try {
    return await chrome.windows.getLastFocused({ windowTypes: ['normal'] })
  } catch {
    return null
  }
}

/**
 * Pone delante la ventana puente, centrada sobre la del usuario, y la recarga.
 *
 * Son dos llamadas porque Chrome no deja cambiar posición y tamaño a la vez
 * que se saca una ventana de minimizada.
 *
 * La recarga es lo que hace aparecer el selector de certificado: en macOS,
 * el que nació con la ventana minimizada no se pinta al restaurarla, solo
 * cuando la ventana recibe un evento del sistema (cambiar de escritorio, por
 * ejemplo). Recargando, la petición que lo pide empieza ya con la ventana
 * visible.
 *
 * @param {number} windowId
 * @param {number} tabId
 * @param {boolean} reload - Solo hace falta si no se alcanzó el panel; con
 *   la pantalla de login ya pintada, recargar solo la haría parpadear.
 */
async function showBridgeWindow(windowId, tabId, reload) {
  const delante = await frontWindow()
  await chrome.windows.update(windowId, { state: 'normal' })
  await chrome.windows.update(windowId, {
    focused: true,
    ...LOGIN_WINDOW,
    ...centeredBounds(delante, LOGIN_WINDOW),
  })
  if (reload) await chrome.tabs.reload(tabId)
}

/** Abre el panel en una ventana emergente visible, centrada sobre la del usuario. */
async function openLoginWindow(origin) {
  return chrome.windows.create({
    url: `${origin}/`,
    type: 'popup',
    focused: true,
    ...LOGIN_WINDOW,
    ...centeredBounds(await frontWindow(), LOGIN_WINDOW),
  })
}

/**
 * Pone el panel delante en una ventana aparte y espera a que haya sesión.
 *
 * Ahí pasan las dos cosas que la extensión no puede hacer por el usuario:
 * elegir el certificado de cliente —el selector de Chrome sale solo al cargar
 * la dirección— y teclear la contraseña en el login del panel, que es el
 * sitio al que pertenece. Mientras tanto se sondea `/api/me`.
 *
 * La ventana es la propia puente cuando la abrió la extensión: se saca de
 * minimizada y, al entrar, se deja para que quien llama la cierre cuando
 * acabe de preguntar. Si la puente es una pestaña del usuario, se abre una
 * ventana nueva y se cierra en cuanto hay sesión.
 *
 * No va en el popup de la extensión porque el popup se cierra al perder el
 * foco, y el selector de certificado se lo lleva.
 *
 * @param {string} origin
 * @param {{tabId: number, opened: boolean, windowId?: number}} bridge
 * @param {'login'|'unreachable'} estado - Lo que contestó la puente.
 * @returns {Promise<number>} La pestaña donde se inició sesión.
 */
async function loginInWindow(origin, bridge, estado) {
  let tabId = bridge.tabId
  let windowId = bridge.windowId
  const propia = !bridge.opened
  if (propia) {
    const ventana = await openLoginWindow(origin)
    tabId = ventana.tabs[0].id
    windowId = ventana.id
  } else {
    await showBridgeWindow(windowId, tabId, estado === 'unreachable')
  }

  let cerrada = false
  const alCerrar = (id) => {
    if (id === windowId) cerrada = true
  }
  chrome.windows.onRemoved.addListener(alCerrar)
  try {
    const limite = Date.now() + LOGIN_TIMEOUT_MS
    while (Date.now() < limite) {
      await new Promise((resolve) => setTimeout(resolve, LOGIN_POLL_MS))
      if (cerrada) {
        throw new AuthError('Se cerró la ventana del panel sin iniciar sesión.')
      }
      if ((await probeSession(tabId)) === 'ok') {
        if (propia) await chrome.windows.remove(windowId).catch(() => {})
        return tabId
      }
    }
    // La ventana se queda como está: cerrarla mientras el usuario puede estar
    // tecleando la contraseña es peor que dejar una de más.
    const agotado = new AuthError('Se agotó la espera: no se inició sesión en el panel.')
    agotado.keepWindow = true
    throw agotado
  } finally {
    chrome.windows.onRemoved.removeListener(alCerrar)
  }
}

// La ventana de login que esté abierta. Abrir el popup dos veces, o abrir un
// proyecto mientras se refresca la lista, no debe sacar dos ventanas: la
// segunda petición espera a la misma.
let loginEnCurso = null

function loginOnce(origin, bridge, estado) {
  if (!loginEnCurso) {
    loginEnCurso = loginInWindow(origin, bridge, estado).finally(() => {
      loginEnCurso = null
    })
  }
  return loginEnCurso
}

/**
 * Pide los proyectos al panel a través de una de sus pestañas, pasando antes
 * por la ventana de login si no hay sesión o no se alcanza el panel.
 *
 * @param {string} origin
 * @returns {Promise<{projects: Array, bridge: {tabId: number, opened: boolean, windowId?: number}, loggedIn: boolean}>}
 */
async function loadProjects(origin) {
  let bridge = await panelBridge(origin)
  let loggedIn = false
  try {
    const estado = await waitForSession(bridge, BRIDGE_PATIENCE_MS)
    if (estado !== 'ok') {
      const donde = await loginOnce(origin, bridge, estado)
      loggedIn = true
      if (donde !== bridge.tabId) bridge = await renewBridge(origin, bridge)
      if ((await waitForSession(bridge, RENEWED_PATIENCE_MS)) !== 'ok') {
        throw new ExtensionError('Se inició sesión, pero el panel sigue sin responder.')
      }
    }
    const salida = await askPanel(bridge.tabId, getInPage, '/api/projects')
    if (!Array.isArray(salida)) {
      throw new ExtensionError('El panel devolvió algo que no es una lista de proyectos.')
    }
    await writeProjects(salida)
    return { projects: salida, bridge, loggedIn }
  } catch (err) {
    // La puente que abrió la extensión se abrió solo para preguntar: si la
    // pregunta falla, no tiene por qué quedarse, salvo que sea la ventana de
    // login con el usuario aún dentro (`keepWindow`).
    if (!err.keepWindow) await closeBridge(bridge)
    throw err
  }
}

/**
 * Deja la pestaña puente servible después de un login hecho en otra parte.
 *
 * La puente se quedó como estaba antes de entrar: con la pantalla de login,
 * con la página de error del certificado o esperando al selector. La que abrió
 * la extensión se tira y se abre otra; la del usuario se recarga, que no
 * pierde nada porque no estaba enseñando el panel.
 *
 * @param {string} origin
 * @param {{tabId: number, opened: boolean, windowId?: number}} bridge
 * @returns {Promise<{tabId: number, opened: boolean, windowId?: number}>}
 */
async function renewBridge(origin, bridge) {
  if (bridge.opened) {
    await closeBridge(bridge)
    return panelBridge(origin)
  }
  const cargada = waitForLoad(bridge.tabId)
  try {
    await chrome.tabs.reload(bridge.tabId)
  } catch {
    return panelBridge(origin)
  }
  await cargada
  return bridge
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

  // Si falta la sesión se pide en la ventana de login y se espera: la
  // apertura sigue sola en cuanto el usuario entra.
  const { projects, bridge } = await loadProjects(origin)
  const avisos = []
  let project
  try {
    project = projects.find((p) => p.id === projectId)
    if (!project) {
      throw new ExtensionError('Ese proyecto ya no existe en el panel.')
    }
    const avisoTerminal = await ensureProjectReady(bridge.tabId, project)
    if (avisoTerminal) avisos.push(avisoTerminal)
  } finally {
    // La puente de la extensión vive en una ventana emergente, y una pestaña
    // de ahí no se puede llevar a un grupo: se cierra y el grupo abre las suyas.
    await closeBridge(bridge)
  }
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

  // Las pestañas nuevas van a la ventana del grupo, o a la normal que tuvo el
  // foco por última vez: dicho explícitamente, porque la «actual» para el
  // service worker podría ser la ventana emergente de login.
  const windowId =
    existente === null
      ? (await frontWindow())?.id
      : (await chrome.tabGroups.get(existente)).windowId
  const nuevas = []
  for (const url of open) {
    const creada = await chrome.tabs.create({ url, active: false, windowId })
    nuevas.push(creada.id)
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
    // Refrescar pasa al abrir el popup. Sin sesión abre la ventana de login,
    // que se lleva el foco y cierra el popup; así que, al volver, se vuelve a
    // abrir el popup para que la lista aparezca sin otro clic.
    refreshProjects: async () => {
      const origin = await readPanelOrigin()
      if (!origin) {
        throw new ExtensionError('Falta la dirección del panel: ábrela en las opciones.')
      }
      const { projects, bridge, loggedIn } = await loadProjects(origin)
      await closeBridge(bridge)
      if (loggedIn) await chrome.action.openPopup().catch(() => {})
      return { projects }
    },
    cachedProjects: async () => ({ projects: await readProjects() }),
  }
  const accion = acciones[message?.type]
  if (!accion) return false

  accion()
    .then((data) => sendResponse({ ok: true, ...data }))
    // `needsLogin` es lo que deja al popup ofrecer el botón de entrar en vez
    // de enseñar un error contra el que no se puede hacer nada.
    .catch((err) =>
      sendResponse({
        ok: false,
        error: err.message,
        needsLogin: err instanceof AuthError,
      }),
    )
  // `true`: la respuesta llega más tarde, en la promesa.
  return true
})
