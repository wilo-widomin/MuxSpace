import { normalizePanelOrigin, originPattern } from './lib/panel.js'
import { readPanelOrigin, writePanelOrigin } from './lib/storage.js'

const campo = document.getElementById('origen')
const aviso = document.getElementById('aviso')

function mostrarAviso(texto, esError = false) {
  aviso.textContent = texto
  aviso.classList.toggle('error', esError)
  aviso.hidden = !texto
}

readPanelOrigin().then((origen) => {
  campo.value = origen
})

document.getElementById('formulario').addEventListener('submit', async (e) => {
  e.preventDefault()
  const origen = normalizePanelOrigin(campo.value)
  if (!origen) {
    mostrarAviso('Esa dirección no se entiende. Ejemplo: panel.mired', true)
    return
  }

  // El permiso se pide AQUÍ y solo para esta dirección, no en el manifiesto
  // para "todos los sitios": la extensión solo tiene que poder leer el panel
  // del usuario.
  const concedido = await chrome.permissions.request({
    origins: [originPattern(origen)],
  })
  if (!concedido) {
    mostrarAviso('Sin ese permiso la extensión no puede leer el panel.', true)
    return
  }

  await writePanelOrigin(origen)
  campo.value = origen
  mostrarAviso(`Guardado: ${origen}`)
})
