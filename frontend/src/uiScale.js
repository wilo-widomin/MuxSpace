// Tamaño del panel en ESTE aparato.
//
// Existe para no tener que usar el zoom del navegador. Con el zoom de Chrome
// a 150 %, cada letra de la terminal se pinta una fracción de píxel más
// ancha de lo que xterm midió; repartido en doscientas columnas, la fila se
// salía casi 3 px por la derecha y xterm, que recorta cada fila a su ancho,
// se comía media última letra. Aquí, en cambio, crece el tamaño de la letra
// y el navegador sigue al 100 %: cada letra cae en píxeles enteros.
//
// Se guarda en localStorage y no en el servidor a propósito: el mismo panel
// se abre desde un portátil y desde una tableta, y el tamaño cómodo en uno
// es enorme en el otro.
//
// Todo lo que va en `rem` (casi todo Tailwind) crece solo al cambiar el
// tamaño de letra de `<html>`. La terminal no: xterm recibe su tamaño en
// píxeles, así que escucha el evento SCALE_EVENT y vuelve a medir.

export const SCALES = [1, 1.25, 1.5, 1.75, 2]

const STORAGE_KEY = 'muxspace:scale'
export const SCALE_EVENT = 'muxspace:scale'

// Tamaño de letra de la terminal al 100 %.
const TERMINAL_FONT_PX = 13

export function readScale() {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY))
    if (SCALES.includes(saved)) return saved
  } catch {
    /* sin localStorage (modo privado): tamaño normal */
  }
  return 1
}

export function terminalFontSize(scale = readScale()) {
  return Math.round(TERMINAL_FONT_PX * scale)
}

/** Aplica el tamaño a la página. Se llama al arrancar y al elegir otro. */
export function applyScale(scale = readScale()) {
  document.documentElement.style.fontSize = `${16 * scale}px`
}

export function setScale(scale) {
  if (!SCALES.includes(scale)) return
  try {
    localStorage.setItem(STORAGE_KEY, String(scale))
  } catch {
    /* sin localStorage: el cambio solo dura lo que la pestaña */
  }
  applyScale(scale)
  window.dispatchEvent(new CustomEvent(SCALE_EVENT, { detail: scale }))
}
