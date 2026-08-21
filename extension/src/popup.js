// El popup no sabe nada del panel: pide al service worker y pinta.

import { filterProjects } from './lib/projects.js'

const lista = document.getElementById('proyectos')
const aviso = document.getElementById('aviso')
const buscar = document.getElementById('buscar')

// Última lista conocida, sin filtrar. El buscador filtra sobre esto en vez de
// volver a preguntar al panel: escribir tiene que responder al instante.
let proyectos = []

function mostrarAviso(texto, esError = false) {
  aviso.textContent = texto
  aviso.classList.toggle('error', esError)
  aviso.hidden = !texto
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

async function refrescar() {
  mostrarAviso('Preguntando al panel…')
  const respuesta = await chrome.runtime.sendMessage({ type: 'refreshProjects' })
  if (!respuesta?.ok) {
    mostrarAviso(respuesta?.error || 'No se pudo leer el panel.', true)
    return
  }
  proyectos = respuesta.projects
  pintar()
}

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

// Al abrir se pinta la copia guardada —es instantáneo— y en paralelo se pide
// la lista de verdad. Si no hay copia, solo queda esperar al panel.
chrome.runtime.sendMessage({ type: 'cachedProjects' }).then((respuesta) => {
  if (respuesta?.ok && respuesta.projects.length > 0) {
    proyectos = respuesta.projects
    pintar()
  }
  refrescar()
})
