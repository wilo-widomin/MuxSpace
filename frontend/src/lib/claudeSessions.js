// Lógica pura de la pantalla de sesiones de Claude Code: sin React ni red,
// para poder probarla sola.

import { formatDate } from '../worklog.js'

// Los cuatro tipos de contenido que se pueden buscar, en el orden en que se
// ofrecen. Por defecto solo el texto: es lo que se escribió y se contestó.
export const KINDS = ['text', 'thinking', 'tool_use', 'tool_result']

export const DEFAULT_FILTERS = {
  role: '',
  kinds: ['text'],
  regex: false,
  subagents: false,
  sort: 'date',
}

// Cuerpo de la búsqueda. Sin consulta no hay búsqueda (devuelve null); sin
// ningún tipo marcado se vuelve a `text`, que es lo que el servidor haría de
// todos modos. El proyecto viaja por id: la carpeta la resuelve el servidor.
export function buildSearchBody(query, filters, projectId) {
  const q = (query || '').trim()
  if (!q) return null
  const kinds = KINDS.filter((k) => filters.kinds.includes(k))
  return {
    q,
    project_id: projectId || null,
    role: filters.role || '',
    regex: Boolean(filters.regex),
    kinds: kinds.length ? kinds : ['text'],
    subagents: Boolean(filters.subagents),
    sort: filters.sort === 'relevance' ? 'relevance' : 'date',
  }
}

// Marca o desmarca un tipo de contenido sin dejar la lista vacía.
export function toggleKind(kinds, kind) {
  if (kinds.includes(kind)) {
    const resto = kinds.filter((k) => k !== kind)
    return resto.length ? resto : kinds
  }
  return KINDS.filter((k) => k === kind || kinds.includes(k))
}

// Fecha dd/mm/aaaa de una marca ISO del API (`2026-11-27T13:51:42.448Z`).
// `formatDate` con una cadena reordena `AAAA-MM-DD` sin pasar por `Date`, y
// con una ISO completa saldría `27T13:51…/11/2026`: se pasa un `Date`.
export function formatIsoDate(iso) {
  if (!iso) return ''
  const fecha = new Date(iso)
  return Number.isNaN(fecha.getTime()) ? '' : formatDate(fecha)
}

// Nombre corto de un proyecto a partir de su ruta: el último tramo.
export function projectName(path) {
  const limpio = (path || '').replace(/\/+$/, '')
  return limpio.split('/').pop() || limpio
}

// Qué pintar cuando una petición falla. El 503 (sesiones apagadas) enseña el
// mensaje y el comando del API tal cual, y NADA intenta encenderlas.
export function describeError(err) {
  if (err && err.code === 'err.claude_sessions_disabled') {
    return {
      kind: 'disabled',
      message: err.body?.mensaje || '',
      command: err.body?.detail || '',
    }
  }
  return { kind: 'error', message: '', command: '' }
}

// Clave de traducción del autor de un mensaje. El API puede traer roles que
// la pantalla no conoce: se pintan como «sistema» en vez de quedarse sin
// texto.
export function roleKey(role) {
  return ['user', 'assistant', 'summary'].includes(role) ? role : 'system'
}
