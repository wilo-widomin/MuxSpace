import { describe, expect, it } from 'vitest'

import {
  LOGIN_STARTED,
  centeredBounds,
  isLoginStarted,
  isNoReceiverError,
  loginAction,
  loginFocusUpdates,
  loginWindowPlan,
  sessionState,
} from './login.js'

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

describe('loginWindowPlan', () => {
  it('con sesión no hay ventana que enseñar', () => {
    expect(loginWindowPlan({ opened: true }, 'ok')).toBe('none')
    expect(loginWindowPlan({ opened: false }, 'ok')).toBe('none')
  })

  it('una puente de la extensión se sustituye por una ventana visible, sea login o certificado', () => {
    expect(loginWindowPlan({ opened: true }, 'login')).toBe('replace')
    expect(loginWindowPlan({ opened: true }, 'unreachable')).toBe('replace')
  })

  it('una pestaña del usuario no se toca: la ventana se abre aparte', () => {
    expect(loginWindowPlan({ opened: false }, 'login')).toBe('open')
    expect(loginWindowPlan({ opened: false }, 'unreachable')).toBe('open')
  })
})

describe('loginAction', () => {
  it('sin login en curso se empieza uno', () => {
    expect(loginAction(false)).toBe('start')
  })

  it('con un login en curso se une a él, sin puente nueva', () => {
    expect(loginAction(true)).toBe('join')
  })
})

describe('loginFocusUpdates', () => {
  it('una ventana tapada solo recibe el foco', () => {
    expect(loginFocusUpdates({ state: 'normal' })).toEqual([
      { focused: true, drawAttention: true },
    ])
  })

  it('una minimizada se restaura antes, en llamada aparte', () => {
    expect(loginFocusUpdates({ state: 'minimized' })).toEqual([
      { state: 'normal' },
      { focused: true, drawAttention: true },
    ])
  })

  it('sin datos de la ventana se intenta el foco', () => {
    expect(loginFocusUpdates(null)).toEqual([{ focused: true, drawAttention: true }])
  })
})

describe('aviso de login al popup', () => {
  it('reconoce solo el mensaje loginStarted', () => {
    expect(isLoginStarted({ type: LOGIN_STARTED })).toBe(true)
    expect(isLoginStarted({ type: 'refreshProjects' })).toBe(false)
    expect(isLoginStarted(undefined)).toBe(false)
    expect(isLoginStarted(null)).toBe(false)
  })

  it('tolera que no haya popup escuchando', () => {
    expect(
      isNoReceiverError(new Error('Could not establish connection. Receiving end does not exist.')),
    ).toBe(true)
    expect(
      isNoReceiverError(new Error('The message port closed before a response was received.')),
    ).toBe(true)
    expect(isNoReceiverError(new Error('otra cosa'))).toBe(false)
    expect(isNoReceiverError(undefined)).toBe(false)
  })
})
