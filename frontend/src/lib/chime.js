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
 * @param {number} volume - Ganancia de pico, 0..1.
 */
export function chime(volume = 0.3) {
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

  // Tres notas ascendentes (La5, Do#6, Mi6): un arpegio mayor, que se lee
  // como "atiende" y no como "error". Con dos notas se confundía con el
  // pitido de cualquier otra cosa; la tercera es lo que lo convierte en una
  // frase reconocible desde la habitación de al lado.
  //
  // Cada nota lleva su OCTAVA por encima a un quinto del volumen. Ese
  // armónico es lo que le da timbre de campana y lo que la hace destacar
  // sobre el ruido de fondo sin subir el volumen hasta molestar: una senoide
  // pelada es fácil de perder, y una onda cuadrada —el otro modo de
  // destacar— suena a alarma de incendios.
  const t0 = c.currentTime
  const NOTAS = [
    [880, 0],
    [1108.7, 0.1],
    [1318.5, 0.2],
  ]
  for (const [freq, retraso] of NOTAS) {
    // La última nota se sostiene más: es la que queda sonando cuando ya has
    // levantado la cabeza, y es la que decide si el aviso se oyó o no.
    const cola = retraso === 0.2 ? 0.75 : 0.4
    for (const [multiplo, peso] of [
      [1, 1],
      [2, 0.2],
    ]) {
      const osc = c.createOscillator()
      const gain = c.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq * multiplo
      const inicio = t0 + retraso
      gain.gain.setValueAtTime(0.0001, inicio)
      gain.gain.exponentialRampToValueAtTime(volume * peso, inicio + 0.012)
      gain.gain.exponentialRampToValueAtTime(0.0001, inicio + cola)
      osc.connect(gain).connect(c.destination)
      osc.start(inicio)
      osc.stop(inicio + cola + 0.05)
    }
  }
}
