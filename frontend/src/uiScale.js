// Tamaño del panel en ESTE aparato.
//
// Existe para no tener que usar el zoom del navegador: Willy trabajaba con
// Chrome al 150 % y así puede dejarlo al 100 % con la letra del mismo tamaño.
// (El corte de la última letra que se vio entonces no era del zoom; ver la
// regla de `.xterm-rows` en index.css.)
//
// Se guarda en localStorage y no en el servidor a propósito: el mismo panel
// se abre desde un portátil y desde una tableta, y el tamaño cómodo en uno
// es enorme en el otro.
//
// Todo lo que va en `rem` (casi todo Tailwind) crece solo al cambiar el
// tamaño de letra de `<html>`. Los iconos también, porque su `width` y su
// `height` van en `rem` y no en píxeles. La terminal no: xterm recibe su tamaño en
// píxeles, así que escucha el evento SCALE_EVENT y vuelve a medir.

// De 10 en 10: entre 125 y 150 % estaba justo el tamaño que Willy quería.
export const SCALES = [1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2]

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
