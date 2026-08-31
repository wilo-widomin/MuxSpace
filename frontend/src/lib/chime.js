// Campanilla de aviso: dos notas cortas, sintetizadas en el navegador.
//
// No hay fichero de audio a propósito. Un .wav habría que servirlo, cachearlo
// y contarlo en la CSP; esto son treinta líneas que suenan igual en el
// portátil y en la tablet, y pesan cero.
//
// **El navegador no deja sonar sin permiso.** Hasta que el usuario no ha
// tocado la página, un AudioContext nace en `suspended` y cualquier sonido se
// descarta en silencio. Por eso `armChime()` se engancha al primer gesto que
// haya —un clic, una tecla— y deja el contexto listo para cuando llegue el
// aviso, que es justo el momento en que ya no habrá ningún gesto que
// aprovechar.

let ctx = null
// Último instante en que sonó, para no encadenar campanillas: varios avisos
// seguidos son una sola noticia y diez pitidos en fila son una alarma.
let ultimo = 0

const MIN_GAP_MS = 3000

function contexto() {
  if (ctx) return ctx
  const Ctor = window.AudioContext || window.webkitAudioContext
  if (!Ctor) return null
  try {
    ctx = new Ctor()
  } catch {
    ctx = null
  }
  return ctx
}

/**
 * Prepara el audio en el primer gesto del usuario y devuelve el desenganche.
 *
 * Se llama una vez, al montar el panel. Sin esto la primera campanilla no
 * suena nunca: llega cuando el usuario está mirando otra cosa.
 */
export function armChime() {
  const despertar = () => {
    const c = contexto()
    if (c && c.state === 'suspended') c.resume().catch(() => {})
  }
  window.addEventListener('pointerdown', despertar)
  window.addEventListener('keydown', despertar)
  return () => {
    window.removeEventListener('pointerdown', despertar)
    window.removeEventListener('keydown', despertar)
  }
}

/**
 * Toca la campanilla. Silenciosa si el navegador aún no ha dado permiso.
 *
 * @param {number} volume - Ganancia de pico, 0..1. Discreta por defecto.
 */
export function chime(volume = 0.12) {
  const c = contexto()
  if (!c) return
  const ahora = Date.now()
  if (ahora - ultimo < MIN_GAP_MS) return
  ultimo = ahora
  if (c.state === 'suspended') {
    // Puede resolver tarde o no resolver: el sonido de ESTE aviso se pierde,
    // pero el contexto queda despierto para el siguiente.
    c.resume().catch(() => {})
    if (c.state === 'suspended') return
  }

  // Dos notas ascendentes (La5, Mi6) con caída exponencial: se lee como
  // "atiende" y no como "error". Ondas senoidales, sin armónicos: un pitido
  // cuadrado en una habitación silenciosa es una alarma de incendios.
  const t0 = c.currentTime
  for (const [freq, retraso] of [
    [880, 0],
    [1318.5, 0.09],
  ]) {
    const osc = c.createOscillator()
    const gain = c.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    const inicio = t0 + retraso
    gain.gain.setValueAtTime(0.0001, inicio)
    gain.gain.exponentialRampToValueAtTime(volume, inicio + 0.01)
    gain.gain.exponentialRampToValueAtTime(0.0001, inicio + 0.32)
    osc.connect(gain).connect(c.destination)
    osc.start(inicio)
    osc.stop(inicio + 0.35)
  }
}
