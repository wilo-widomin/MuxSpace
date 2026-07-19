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
      // `other` es obligatorio: es la forma a la que cae el runtime cuando
      // no encuentra la que toca. Las demás formas que distingue el idioma
      // (p. ej. "many", que en es/fr/it/pt solo aplica a cantidades enormes
      // escritas de forma compacta —"1 millón de ventanas"—) se avisan pero
      // no bloquean: con un contador de ventanas nunca se alcanzan y `other`
      // se lee bien.
      if (catalog[key].other == null) {
        report(lang, `${key}: falta la forma plural obligatoria "other"`)
      }
      const missing = [...pluralForms(lang)].filter(
        (form) => catalog[key][form] == null,
      )
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
// Solo detecta las literales `t('clave')`; una clave construida en tiempo de
// ejecución no se puede comprobar así, y por eso no las usamos.
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
for (const file of sources) {
  const code = readFileSync(file, 'utf8')
  for (const m of code.matchAll(/(?:\bt|\.current)\(\s*'([\w.]+)'/g)) {
    if (!used.has(m[1])) used.set(m[1], relative(ROOT, file))
  }
}
for (const [key, file] of used) {
  if (!(key in base)) problems.push(`[código] ${file}: clave inexistente ${key}`)
}
// Aviso, no error: un catálogo puede llevar claves que solo usa el backend
// (los `err.*` no aparecen en el código del frontend).
const unused = baseKeys.filter((k) => !used.has(k) && !k.startsWith('err.'))
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
