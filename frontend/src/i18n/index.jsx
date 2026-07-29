// Internacionalización del panel.
//
// Módulo propio en vez de react-i18next: de un motor ICU completo solo
// necesitamos lookup por clave, interpolación `{name}` y un único plural
// (el contador de ventanas), y `Intl.PluralRules` ya viene en el navegador.
//
// El catálogo `es` es la FUENTE DE VERDAD: el resto de idiomas se derivan
// de él y cualquier clave que les falte cae de vuelta al español, de modo
// que una traducción incompleta degrada a texto en español y nunca a la
// clave cruda.
//
// Los errores del backend llegan como `{code, params}` y se traducen aquí
// (ver `backend/errors.py`): el servidor es agnóstico al idioma.
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api.js'
import de from './locales/de.json'
import en from './locales/en.json'
import es from './locales/es.json'
import fr from './locales/fr.json'
import it from './locales/it.json'
import pt from './locales/pt.json'

// Idioma base: el catálogo completo del que salen los demás.
export const BASE_LANG = 'es'

const CATALOGS = { es, en, fr, de, pt, it }

// Nombres en su propio idioma: un selector de idioma en el que las
// opciones estén traducidas al idioma ACTUAL no sirve de nada a quien no
// entiende el idioma actual.
export const LANGUAGES = [
  { code: 'es', label: 'Español' },
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'pt', label: 'Português' },
  { code: 'it', label: 'Italiano' },
]

const STORAGE_KEY = 'muxspace:lang'

/** Idioma a usar: elección explícita → idioma del navegador → base. */
export function resolveLang() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && CATALOGS[saved]) return saved
  } catch {
    /* sin localStorage (modo privado): seguimos con el del navegador */
  }
  const candidates =
    typeof navigator === 'undefined'
      ? []
      : [navigator.language, ...(navigator.languages || [])]
  for (const tag of candidates) {
    // "es-419", "pt-BR" → "es", "pt": distinguimos por idioma, no por región.
    const code = String(tag || '')
      .toLowerCase()
      .split('-')[0]
    if (CATALOGS[code]) return code
  }
  return BASE_LANG
}

// "Hola {name}" + {name: 'x'} → "Hola x". Un placeholder sin valor se deja
// tal cual: es más fácil de detectar en pantalla que un hueco vacío.
function interpolate(text, params) {
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (match, key) =>
    key in params ? String(params[key]) : match,
  )
}

// Una entrada del catálogo puede ser un string o, cuando el texto depende
// de una cantidad, un objeto con las formas plurales de ESE idioma
// ({one, other} en español; el ruso o el polaco tendrían más). La forma
// que toca la elige Intl.PluralRules, no nosotros.
function pick(entry, lang, params) {
  if (typeof entry === 'string') return entry
  if (entry && typeof entry === 'object') {
    const count = Number(params?.count)
    if (Number.isFinite(count)) {
      const form = new Intl.PluralRules(lang).select(count)
      if (entry[form] != null) return entry[form]
    }
    if (entry.other != null) return entry.other
  }
  return null
}

/** Crea la función de traducción de un idioma. */
export function makeT(lang) {
  const catalog = CATALOGS[lang] || CATALOGS[BASE_LANG]
  const base = CATALOGS[BASE_LANG]
  return function t(key, params) {
    const entry = key in catalog ? catalog[key] : base[key]
    const text = pick(entry, lang, params)
    // Sin traducción ni en el idioma ni en el base: la clave es lo único
    // que podemos mostrar, y delata el fallo en vez de esconderlo.
    if (text == null) return key
    return interpolate(text, params)
  }
}

/**
 * Texto de un error para el usuario.
 *
 * Un `ApiError` con `code` se traduce; el `technical` (stderr de tmux y
 * demás, que sale en el idioma del sistema) va detrás como detalle
 * secundario en vez de sustituir al mensaje localizado.
 */
export function makeTError(t) {
  return function tError(err) {
    if (!err) return t('err.unknown')
    if (err instanceof ApiError && err.code) {
      const message = t(err.code, err.params)
      return err.technical ? `${message} (${err.technical})` : message
    }
    return err.message || t('err.unknown')
  }
}

const LangContext = createContext(null)

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(resolveLang)

  const setLang = (next) => {
    setLangState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* sin localStorage: la elección solo dura lo que la pestaña */
    }
  }

  const value = useMemo(() => {
    const t = makeT(lang)
    return { lang, setLang, t, tError: makeTError(t) }
  }, [lang])

  // `<html lang>` es lo que usan los lectores de pantalla para elegir voz
  // y el navegador para partir palabras; el título vive aquí porque
  // index.html ya no puede saber en qué idioma se va a pintar la página.
  useEffect(() => {
    document.documentElement.lang = lang
    document.title = value.t('app.title')
  }, [lang, value])

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

/** Hook de traducción: `const { t, tError, lang, setLang } = useT()`. */
export function useT() {
  const ctx = useContext(LangContext)
  if (!ctx) throw new Error('useT() requiere un <LangProvider> por encima')
  return ctx
}
