// El popup no sabe nada del panel: pide al service worker y pinta.

import { originPattern } from './lib/panel.js'
import { isLoginStarted } from './lib/login.js'
import { filterProjects, listView } from './lib/projects.js'
import { readPanelOrigin } from './lib/storage.js'

const lista = document.getElementById('proyectos')
const aviso = document.getElementById('aviso')
const buscar = document.getElementById('buscar')
const entrar = document.getElementById('entrar')

// Última lista conocida, sin filtrar. El buscador filtra sobre esto en vez de
// volver a preguntar al panel: escribir tiene que responder al instante.
let proyectos = []

function mostrarAviso(texto, esError = false, pedirLogin = false) {
  aviso.textContent = texto
  aviso.classList.toggle('error', esError)
  aviso.hidden = !texto
  entrar.hidden = !pedirLogin
}

/** Repinta la lista con el filtro que haya escrito ahora mismo. */
function pintar() {
  const visibles = filterProjects(proyectos, buscar.value)
  lista.replaceChildren()
  if (proyectos.length === 0) {
    mostrarAviso('No hay proyectos. Créalos en el panel.')
    return
  }
  if (visibles.length === 0) {
    mostrarAviso(`Ningún proyecto contiene «${buscar.value.trim()}».`)
    return
  }
  mostrarAviso('')
  for (const proyecto of visibles) {
    const item = document.createElement('li')
    const boton = document.createElement('button')
    boton.type = 'button'
    boton.append(document.createTextNode(proyecto.title))
    const cuantos = (proyecto.links || []).length
    const detalle = document.createElement('span')
    detalle.className = 'enlaces'
    detalle.textContent =
      cuantos === 0
        ? 'Solo el panel'
        : `Panel + ${cuantos} enlace${cuantos === 1 ? '' : 's'}`
    boton.append(detalle)
    boton.addEventListener('click', () => abrir(proyecto.id, boton))
    item.append(boton)
    lista.append(item)
  }
}

async function abrir(projectId, boton) {
  boton.disabled = true
  mostrarAviso('Abriendo…')
  const respuesta = await chrome.runtime.sendMessage({ type: 'openProject', projectId })
  boton.disabled = false
  if (!respuesta?.ok) {
    // Sin sesión, el service worker ya ha abierto la ventana de login y
    // seguirá con la apertura solo; este mensaje casi nunca llega a verse,
    // porque al pasar el foco a esa ventana el popup se cierra.
    mostrarAviso(respuesta?.error || 'No se pudo abrir el proyecto.', true)
    return
  }
  if (respuesta.warning) {
    // El grupo se abrió pero algo no salió: se queda a la vista para que se
    // pueda leer, en vez de cerrarse y perderlo.
    mostrarAviso(respuesta.warning, true)
    return
  }
  // El grupo ya está delante: el popup no pinta nada más.
  window.close()
}

// Tope del atajo: si falta el certificado, la petición puede quedarse en
// silencio, y el atajo no debe retrasar el flujo de siempre más que esto.
const SHORTCUT_TIMEOUT_MS = 3000

/**
 * Atajo: pedir la lista directamente desde esta página, sin abrir ventanas.
 *
 * Solo sirve si el `fetch` de la página del popup lleva la cookie de sesión y
 * el certificado de cliente; no está comprobado que lo haga en todos los
 * casos. Por eso es un atajo y nada más: cualquier cosa que no sea una
 * respuesta 200 con datos válidos devuelve `null` y se sigue por el flujo de
 * siempre (el service worker, con su puente y su ventana de login).
 *
 * @returns {Promise<Array|null>} Los proyectos, o `null` si no hubo atajo.
 */
async function projectsByShortcut() {
  try {
    const origin = await readPanelOrigin()
    if (!origin) return null
    // Sin permiso de host ya concedido (se pide en las opciones) no se
    // intenta: pedirlo aquí abriría un aviso sin que el usuario lo espere.
    if (!(await chrome.permissions.contains({ origins: [originPattern(origin)] }))) return null
    const pedir = (ruta) =>
      fetch(`${origin}${ruta}`, {
        credentials: 'include',
        redirect: 'manual',
        signal: AbortSignal.timeout(SHORTCUT_TIMEOUT_MS),
      })
    const yo = await pedir('/api/me')
    if (yo.status !== 200) return null
    const respuesta = await pedir('/api/projects')
    if (respuesta.status !== 200) return null
    const lista = await respuesta.json()
    if (!Array.isArray(lista)) return null
    return lista
  } catch {
    return null
  }
}

async function refrescar() {
  // Mientras no se confirma la sesión no se pinta ninguna lista: ni la de la
  // vez anterior ni la vacía. El aviso es lo único que se ve.
  proyectos = []
  lista.replaceChildren()
  mostrarAviso('Preguntando al panel…')
  const atajo = await projectsByShortcut()
  const respuesta = atajo ? null : await chrome.runtime.sendMessage({ type: 'refreshProjects' })
  const vista = listView(atajo, respuesta)
  if (vista.kind === 'error') {
    // Sin sesión, el service worker abre la ventana de login y este popup se
    // cierra antes de llegar aquí. Si se llega es porque esa ventana se cerró
    // o se agotó la espera: se ofrece volver a intentarlo.
    mostrarAviso(vista.message, true, vista.needsLogin)
    return
  }
  proyectos = vista.projects
  pintar()
}

// El login se hace SIEMPRE en una ventana del panel: la contraseña se teclea
// en el sitio al que pertenece, no en el popup de una extensión. Refrescar ya
// abre esa ventana cuando hace falta, así que el botón solo reintenta.
entrar.addEventListener('click', refrescar)

document.getElementById('refrescar').addEventListener('click', refrescar)
document.getElementById('opciones').addEventListener('click', () => {
  chrome.runtime.openOptionsPage()
})

buscar.addEventListener('input', pintar)

// Enter abre el primero de la lista filtrada. Con el buscador enfocado al
// abrir el popup, un proyecto son tres letras y un Enter sin tocar el ratón.
buscar.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return
  const primero = lista.querySelector('button')
  if (primero) primero.click()
})

// El service worker avisa en cuanto abre (o pone delante) la ventana de login:
// el login se hace allí, y el popup no tiene nada que enseñar mientras tanto.
// Cerrarse aquí evita quedarse visible con «Preguntando al panel…» hasta que
// Chrome lo cierre por perder el foco. Al volver con sesión, el service worker
// reabre el popup (`openPopup`) con la lista.
chrome.runtime.onMessage.addListener((message) => {
  if (isLoginStarted(message)) window.close()
})

// Al abrir solo se pregunta al panel: la lista se pinta cuando hay sesión
// confirmada, nunca antes.
refrescar()
