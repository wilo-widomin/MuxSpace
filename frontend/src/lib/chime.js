// Campanilla de aviso: sintetizada en el navegador, y configurable.
//
// No hay fichero de audio para los sonidos que trae el panel, a propósito. Un
// .wav habría que servirlo, cachearlo y contarlo en la CSP; esto son unas
// notas en una tabla, suenan igual en el portátil y en la tablet, y pesan
// cero. Quien quiera otra cosa puede subir SU audio, y entonces sí hay un
// fichero: pero es uno solo y lo pidió el usuario.
//
// **El navegador no deja sonar sin permiso.** Hasta que el usuario no ha
// tocado la página, un AudioContext nace en `suspended` y cualquier sonido se
// descarta en silencio. Por eso `armChime()` se engancha al primer gesto que
// haya —un clic, una tecla— y deja el contexto listo para cuando llegue el
// aviso, que es justo el momento en que ya no habrá ningún gesto que
// aprovechar.
//
// La receta (qué suena, a qué volumen) vive en el SERVIDOR y llega por
// `configure()`. Ver `backend/chime_store.py`: el panel se abre desde tres
// aparatos y elegir la campanilla tres veces es elegirla mal dos.

// Los sonidos que trae el panel. Cada uno es una lista de notas —tono en
// hercios, cuándo entra y cuánto tarda en apagarse— más un timbre.
//
// El catálogo vive AQUÍ y no en el backend: el backend no sintetiza nada, así
// que repetir la lista allí solo serviría para que un día no coincidieran. Él
// valida la forma del id; si le llega uno que este catálogo no conoce, suena
// el de por defecto.
export const PRESETS = {
  // El de siempre: arpegio de La mayor, que se lee como "atiende" y no como
  // "error". La última nota se sostiene más porque es la que sigue sonando
  // cuando ya has levantado la cabeza.
  bell: {
    timbre: 'bell',
    notes: [
      { freq: 880, delay: 0, duration: 0.4 },
      { freq: 1108.7, delay: 0.1, duration: 0.4 },
      { freq: 1318.5, delay: 0.2, duration: 0.75 },
    ],
  },
  // Notas secas y sin armónico: suena a madera, no a metal.
  marimba: {
    timbre: 'sine',
    notes: [
      { freq: 1046.5, delay: 0, duration: 0.25 },
      { freq: 1318.5, delay: 0.08, duration: 0.25 },
      { freq: 1568, delay: 0.16, duration: 0.35 },
    ],
  },
  // Las dos notas originales, para quien prefiera el aviso más corto.
  'two-tones': {
    timbre: 'sine',
    notes: [
      { freq: 880, delay: 0, duration: 0.35 },
      { freq: 1318.5, delay: 0.09, duration: 0.35 },
    ],
  },
  // Cae en vez de subir: la segunda nota es más grave y dura más.
  drop: {
    timbre: 'sine',
    notes: [
      { freq: 1568, delay: 0, duration: 0.14 },
      { freq: 784, delay: 0.05, duration: 0.5 },
    ],
  },
  // Grave y discreto, para cuando hay gente alrededor.
  knock: {
    timbre: 'bell',
    notes: [
      { freq: 220, delay: 0, duration: 0.3 },
      { freq: 220, delay: 0.18, duration: 0.35 },
    ],
  },
  // Tres golpes iguales: el más difícil de ignorar.
  alert: {
    timbre: 'sine',
    notes: [
      { freq: 987.8, delay: 0, duration: 0.18 },
      { freq: 987.8, delay: 0.22, duration: 0.18 },
      { freq: 987.8, delay: 0.44, duration: 0.3 },
    ],
  },
}

export const DEFAULT_PRESET = 'bell'

// El ajuste de fábrica, y lo que se usa mientras el del servidor no ha
// llegado: un aviso que no suena porque la preferencia tarda en cargar es un
// aviso perdido.
export const DEFAULT_CONFIG = {
  mode: 'preset',
  preset: DEFAULT_PRESET,
  volume: 0.3,
  muted: false,
  notes: [],
  timbre: 'bell',
  file: null,
}

// URL del audio propio. Es una ruta del backend, mismo origen, así que la
// cubre `default-src 'self'` de la CSP sin tener que abrirle nada.
export const CUSTOM_AUDIO_URL = '/api/chime/audio'

let ctx = null
let config = { ...DEFAULT_CONFIG }
// Último instante en que sonó, para no encadenar campanillas: varios avisos
// seguidos son una sola noticia y diez pitidos en fila son una alarma.
let ultimo = 0

const MIN_GAP_MS = 3000

/**
 * Fija la receta que sonará en los próximos avisos.
 *
 * @param {object} cfg - Ajuste tal como lo devuelve `GET /api/chime`.
 */
export function configure(cfg) {
  config = { ...DEFAULT_CONFIG, ...(cfg || {}) }
}

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
 * Devuelve las notas y el timbre que corresponden a un ajuste.
 *
 * Un preset desconocido —un ajuste guardado por una versión más nueva del
 * panel, o editado a mano— cae al de por defecto en vez de no sonar.
 */
export function recipeOf(cfg) {
  if (cfg.mode === 'custom' && cfg.notes?.length) {
    return { timbre: cfg.timbre || 'bell', notes: cfg.notes }
  }
  return PRESETS[cfg.preset] || PRESETS[DEFAULT_PRESET]
}

function sintetizar(c, { notes, timbre }, volume) {
  const t0 = c.currentTime
  // El armónico de la octava por encima es lo que da timbre de campana y lo
  // que hace que destaque sobre el ruido de fondo sin subir el volumen hasta
  // molestar: una senoide pelada es fácil de perder, y una onda cuadrada —el
  // otro modo de destacar— suena a alarma de incendios.
  const parciales =
    timbre === 'bell'
      ? [
          [1, 1],
          [2, 0.2],
        ]
      : [[1, 1]]
  for (const nota of notes) {
    for (const [multiplo, peso] of parciales) {
      const osc = c.createOscillator()
      const gain = c.createGain()
      osc.type = 'sine'
      osc.frequency.value = nota.freq * multiplo
      const inicio = t0 + nota.delay
      const pico = Math.max(0.0002, volume * peso)
      gain.gain.setValueAtTime(0.0001, inicio)
      gain.gain.exponentialRampToValueAtTime(pico, inicio + 0.012)
      gain.gain.exponentialRampToValueAtTime(0.0001, inicio + nota.duration)
      osc.connect(gain).connect(c.destination)
      osc.start(inicio)
      osc.stop(inicio + nota.duration + 0.05)
    }
  }
}

function reproducirArchivo(volume) {
  // El audio propio no pasa por el AudioContext: un `<audio>` suelto se
  // encarga de decodificar cualquier formato que entienda el navegador, que
  // es justo lo que no queremos reimplementar.
  try {
    const audio = new Audio(CUSTOM_AUDIO_URL)
    audio.volume = Math.min(1, Math.max(0, volume))
    audio.play().catch(() => {})
  } catch {
    // Sin sonido, pero la marca ámbar del tile sigue estando: el aviso no se
    // pierde porque el navegador se niegue a reproducir.
  }
}

/**
 * Toca la campanilla configurada. Silenciosa si el navegador no da permiso.
 *
 * @param {object} [cfg] - Ajuste a usar; por defecto, el configurado.
 * @param {boolean} [force] - Salta el silencio entre avisos (para la
 *   prueba del panel de ajustes, donde encadenar sí es lo que se quiere).
 */
export function chime(cfg = config, { force = false } = {}) {
  if (cfg.muted && !force) return
  if (!force) {
    const ahora = Date.now()
    if (ahora - ultimo < MIN_GAP_MS) return
    ultimo = ahora
  }

  const volume = typeof cfg.volume === 'number' ? cfg.volume : DEFAULT_CONFIG.volume
  if (cfg.mode === 'file' && cfg.file) {
    reproducirArchivo(volume)
    return
  }

  const c = contexto()
  if (!c) return
  if (c.state === 'suspended') {
    // Puede resolver tarde o no resolver: el sonido de ESTE aviso se pierde,
    // pero el contexto queda despierto para el siguiente.
    c.resume().catch(() => {})
    if (c.state === 'suspended') return
  }
  sintetizar(c, recipeOf(cfg), volume)
}

/**
 * Toca un ajuste sin guardarlo y sin esperar al silencio entre avisos.
 *
 * Es el botón "probar": ahí encadenar sonidos es exactamente lo que se
 * quiere, y silenciado o no da igual porque el usuario acaba de pedirlo.
 */
export function previewChime(cfg) {
  chime({ ...DEFAULT_CONFIG, ...cfg }, { force: true })
}
