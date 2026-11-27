import { describe, it, expect } from 'vitest'
import {
  DEFAULT_FILTERS,
  buildSearchBody,
  describeError,
  formatIsoDate,
  projectName,
  roleKey,
  toggleKind,
} from './claudeSessions.js'
import { ApiError } from '../api.js'

describe('buildSearchBody', () => {
  it('sin consulta no hay búsqueda', () => {
    expect(buildSearchBody('', DEFAULT_FILTERS, null)).toBeNull()
    expect(buildSearchBody('   ', DEFAULT_FILTERS, null)).toBeNull()
  })

  it('lleva los filtros y el proyecto por id, nunca una carpeta', () => {
    const body = buildSearchBody(
      '  hola  ',
      {
        role: 'user',
        kinds: ['thinking', 'text'],
        regex: true,
        subagents: true,
        sort: 'relevance',
      },
      'p1',
    )
    expect(body).toEqual({
      q: 'hola',
      project_id: 'p1',
      role: 'user',
      regex: true,
      kinds: ['text', 'thinking'],
      subagents: true,
      sort: 'relevance',
    })
  })

  it('los valores raros caen a los de fábrica', () => {
    const body = buildSearchBody(
      'x',
      { ...DEFAULT_FILTERS, kinds: [], sort: 'azar' },
      undefined,
    )
    expect(body.kinds).toEqual(['text'])
    expect(body.sort).toBe('date')
    expect(body.project_id).toBeNull()
  })
})

describe('toggleKind', () => {
  it('añade en el orden de siempre y quita', () => {
    expect(toggleKind(['text'], 'tool_use')).toEqual(['text', 'tool_use'])
    expect(toggleKind(['text', 'tool_use'], 'thinking')).toEqual([
      'text',
      'thinking',
      'tool_use',
    ])
    expect(toggleKind(['text', 'tool_use'], 'text')).toEqual(['tool_use'])
  })

  it('no deja la lista vacía', () => {
    expect(toggleKind(['text'], 'text')).toEqual(['text'])
  })
})

describe('formatIsoDate', () => {
  it('pinta dd/mm/aaaa con el día local, no la cadena cruda', () => {
    const iso = new Date(2026, 10, 27, 13, 51).toISOString()
    expect(formatIsoDate(iso)).toBe('27/11/2026')
  })

  it('tolera vacíos y basura', () => {
    expect(formatIsoDate('')).toBe('')
    expect(formatIsoDate(undefined)).toBe('')
    expect(formatIsoDate('nada')).toBe('')
  })
})

describe('projectName y roleKey', () => {
  it('último tramo de la ruta', () => {
    expect(projectName('/home/x/proyectos/mvp-lab/')).toBe('mvp-lab')
    expect(projectName('')).toBe('')
  })

  it('un rol desconocido se pinta como sistema', () => {
    expect(roleKey('user')).toBe('user')
    expect(roleKey('summary')).toBe('summary')
    expect(roleKey('tool')).toBe('system')
  })
})

describe('describeError', () => {
  it('el 503 enseña el mensaje y el comando tal cual', () => {
    const err = new ApiError(503, {
      code: 'err.claude_sessions_disabled',
      mensaje: 'Apagadas.',
      detail: 'Para activarlas: touch /x',
    })
    expect(describeError(err)).toEqual({
      kind: 'disabled',
      message: 'Apagadas.',
      command: 'Para activarlas: touch /x',
    })
  })

  it('otros errores no llevan comando', () => {
    expect(
      describeError(new ApiError(502, { code: 'err.claude_sessions_down' })).kind,
    ).toBe('error')
    expect(describeError(null).kind).toBe('error')
  })
})
