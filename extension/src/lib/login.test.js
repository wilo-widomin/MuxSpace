import { describe, expect, it } from 'vitest'

import { centeredBounds, sessionState } from './login.js'

describe('sessionState', () => {
  it('una respuesta buena de /api/me es que hay sesión', () => {
    expect(sessionState({ user: 'willy' })).toBe('ok')
  })

  it('un 401 es que hay que entrar', () => {
    expect(sessionState({ __error: 'HTTP 401', __status: 401 })).toBe('login')
  })

  it('sin poder inyectar (falta el certificado) no se alcanza el panel', () => {
    expect(sessionState(undefined)).toBe('unreachable')
    expect(sessionState(null)).toBe('unreachable')
  })

  it('un error que no es 401 tampoco cuenta como sesión', () => {
    expect(sessionState({ __error: 'HTTP 500', __status: 500 })).toBe('unreachable')
    expect(sessionState({ __error: 'TypeError: Failed to fetch' })).toBe('unreachable')
  })
})

describe('centeredBounds', () => {
  it('centra la ventana sobre la de delante', () => {
    const parent = { left: 100, top: 50, width: 1200, height: 800 }
    expect(centeredBounds(parent, { width: 480, height: 720 })).toEqual({
      left: 460,
      top: 90,
    })
  })

  it('redondea a píxeles enteros', () => {
    const parent = { left: 0, top: 0, width: 1001, height: 801 }
    expect(centeredBounds(parent, { width: 480, height: 720 })).toEqual({
      left: 261,
      top: 41,
    })
  })

  it('sin datos de la ventana de delante, deja que Chrome elija', () => {
    expect(centeredBounds(null, { width: 480, height: 720 })).toBeNull()
    expect(centeredBounds({ left: 0, top: 0 }, { width: 480, height: 720 })).toBeNull()
  })
})
