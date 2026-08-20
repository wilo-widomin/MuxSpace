// El popup no sabe nada del panel: pide al service worker y pinta.

const lista = document.getElementById('proyectos')
const aviso = document.getElementById('aviso')

function mostrarAviso(texto, esError = false) {
  aviso.textContent = texto
  aviso.classList.toggle('error', esError)
  aviso.hidden = !texto
}

/** @param {Array} proyectos */
function pintar(proyectos) {
  lista.replaceChildren()
  if (proyectos.length === 0) {
    mostrarAviso('No hay proyectos. Créalos en el panel.')
    return
  }
  for (const proyecto of proyectos) {
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
  mostrarAviso('')
  pintar(respuesta.projects)
}

document.getElementById('refrescar').addEventListener('click', refrescar)
document.getElementById('opciones').addEventListener('click', () => {
  chrome.runtime.openOptionsPage()
})

// Al abrir se pinta la copia guardada —es instantáneo— y en paralelo se pide
// la lista de verdad. Si no hay copia, solo queda esperar al panel.
chrome.runtime.sendMessage({ type: 'cachedProjects' }).then((respuesta) => {
  if (respuesta?.ok && respuesta.projects.length > 0) pintar(respuesta.projects)
  refrescar()
})
