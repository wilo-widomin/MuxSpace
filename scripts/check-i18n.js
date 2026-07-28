#!/usr/bin/env node
// Comprueba la salud de los catálogos de traducción.
//
// `es.json` es la fuente de verdad; el resto se compara contra él. Sin esto,
// añadir un idioma (o una clave) es un ejercicio de fe: una clave que falte
// degrada en silencio al español y una que sobre no la ve nadie nunca.
//
// Verifica, por idioma:
//   - claves que faltan y claves huérfanas (que ya no existen en es.json),
//   - placeholders `{x}` distintos de los del original,
//   - formas plurales: que estén las que CLDR exige para ESE idioma,
//   - claves usadas en el código (`t('...')`) que no existen en el catálogo.
//
// Uso: node scripts/check-i18n.js   (salida != 0 si hay algún problema)
import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const LOCALES_DIR = join(ROOT, 'frontend', 'src', 'i18n', 'locales')
const SRC_DIR = join(ROOT, 'frontend', 'src')
const BASE = 'es'

const problems = []
const warnings = []
const report = (lang, message) => problems.push(`[${lang}] ${message}`)

const load = (lang) =>
  JSON.parse(readFileSync(join(LOCALES_DIR, `${lang}.json`), 'utf8'))

const placeholders = (value) => {
  const text =
    typeof value === 'string' ? value : Object.values(value || {}).join(' ')
  return new Set([...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))
}

// Formas plurales que CLDR exige para este idioma. Se derivan de
// Intl.PluralRules en vez de mantenerse a mano: es la misma fuente que usa
// el runtime para elegir la forma, así que no pueden discrepar.
const pluralForms = (lang) =>
  new Set(new Intl.PluralRules(lang).resolvedOptions().pluralCategories)

// Formas plurales que este panel no puede alcanzar, así que echarlas en falta
// es ruido y no una traducción pendiente.
//
// `many` en es/fr/it/pt es la categoría de las cantidades enormes escritas de
// forma COMPACTA ("1 millón de ventanas"): CLDR solo la selecciona con
// `Intl.NumberFormat(..., {notation: 'compact'})`. Aquí los dos únicos plurales
// del catálogo cuentan ventanas de tmux y sesiones a borrar, se formatean como
// enteros normales y jamás llegan a esa notación — el runtime cae a `other`,
// que se lee perfectamente.
//
// Se silencia esta forma concreta en vez de inventar traducciones que ningún
// idioma de la lista usa de verdad: ver docs/i18n.md. Si algún día se muestra
// una cantidad en notación compacta, hay que quitar `many` de aquí.
const FORMAS_INALCANZABLES = new Set(['many'])

const base = load(BASE)
const baseKeys = Object.keys(base)
const langs = readdirSync(LOCALES_DIR)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.replace(/\.json$/, ''))

for (const lang of langs) {
  const catalog = load(lang)
  const keys = new Set(Object.keys(catalog))

  for (const key of baseKeys) {
    if (!keys.has(key)) {
      report(lang, `falta la clave: ${key}`)
      continue
    }
    const expected = placeholders(base[key])
    const actual = placeholders(catalog[key])
    for (const ph of expected) {
      if (!actual.has(ph)) report(lang, `${key}: falta el placeholder {${ph}}`)
    }
    for (const ph of actual) {
      if (!expected.has(ph)) report(lang, `${key}: placeholder sobrante {${ph}}`)
    }
    // Una entrada con plural en el original tiene que llevar plural aquí, y
    // con las formas del idioma destino (no con las del español).
    const basePlural = typeof base[key] === 'object'
    const langPlural = typeof catalog[key] === 'object'
    if (basePlural !== langPlural) {
      report(
        lang,
        `${key}: ${basePlural ? 'debería tener formas plurales' : 'no debería tener formas plurales'}`,
      )
    } else if (basePlural) {
      // `other` es obligatorio: es la forma a la que cae el runtime cuando no
      // encuentra la que toca.
      if (catalog[key].other == null) {
        report(lang, `${key}: falta la forma plural obligatoria "other"`)
      }
      const missing = [...pluralForms(lang)]
        .filter((form) => !FORMAS_INALCANZABLES.has(form))
        .filter((form) => catalog[key][form] == null)
      if (missing.length) {
        warnings.push(
          `[${lang}] ${key}: sin forma(s) ${missing.join(', ')} (cae a "other")`,
        )
      }
    }
  }

  for (const key of keys) {
    if (!(key in base)) report(lang, `clave huérfana (no está en ${BASE}): ${key}`)
  }
}

// ---- Claves usadas en el código pero ausentes del catálogo ----
// Detecta las literales `t('clave')` y, por separado, los PREFIJOS de las
// claves que el código construye en tiempo de ejecución —hoy solo
// t(`grid.layout_${modo}`)—. El comentario que había aquí decía que no se
// usaban claves dinámicas; sí se usan, y creérselo llevaba a que las tres
// `grid.layout_*` salieran listadas como "sin uso" y a que el plan las diera
// por borrables. Borrarlas dejaría los tres botones de disposición
// enseñando "grid.layout_auto" como tooltip y como aria-label, porque `t()`
// devuelve la propia clave cuando no la encuentra.
const sources = []
const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) walk(full)
    else if (/\.jsx?$/.test(full)) sources.push(full)
  }
}
walk(SRC_DIR)

const used = new Map()
// Prefijos literales de claves dinámicas: de t(`grid.layout_${x}`) sale
// "grid.layout_". Cualquier clave del catálogo que empiece así cuenta como
// usada, que es lo más que se puede afirmar sin ejecutar el código.
const usedPrefixes = new Map()
for (const file of sources) {
  const code = readFileSync(file, 'utf8')
  for (const m of code.matchAll(/(?:\bt|\.current)\(\s*'([\w.]+)'/g)) {
    if (!used.has(m[1])) used.set(m[1], relative(ROOT, file))
  }
  for (const m of code.matchAll(/(?:\bt|\.current)\(\s*`([\w.]*)\$\{/g)) {
    if (m[1] && !usedPrefixes.has(m[1])) {
      usedPrefixes.set(m[1], relative(ROOT, file))
    }
  }
}
const usedDynamically = (key) =>
  [...usedPrefixes.keys()].some((prefix) => key.startsWith(prefix))
for (const [key, file] of used) {
  if (!(key in base)) problems.push(`[código] ${file}: clave inexistente ${key}`)
}
// Aviso, no error: un catálogo puede llevar claves que solo usa el backend
// (los `err.*` no aparecen en el código del frontend).
const unused = baseKeys.filter(
  (k) => !used.has(k) && !usedDynamically(k) && !k.startsWith('err.'),
)
// Un prefijo dinámico sin ninguna clave detrás es lo contrario: código que
// pide algo que el catálogo no tiene. Eso sí es un problema, y hasta ahora no
// lo veía nadie.
for (const [prefix, file] of usedPrefixes) {
  if (!baseKeys.some((k) => k.startsWith(prefix))) {
    problems.push(
      `[código] ${file}: clave dinámica ${prefix}… sin ninguna clave en ${BASE}`,
    )
  }
}
if (warnings.length) {
  console.warn('Avisos:')
  for (const w of warnings) console.warn(`  ${w}`)
}
if (unused.length) {
  console.warn(`Aviso: ${unused.length} clave(s) sin uso en el código:`)
  for (const key of unused) console.warn(`  - ${key}`)
}

if (problems.length) {
  console.error(`\n${problems.length} problema(s):`)
  for (const p of problems) console.error(`  ${p}`)
  process.exit(1)
}
console.log(
  `OK: ${langs.length} idiomas (${langs.join(', ')}), ${baseKeys.length} claves.`,
)
