// El contrato de errores entre backend y frontend.
//
// Un error del backend NO trae texto para el usuario: trae `{code, params}` y
// lo traduce el cliente. Si este parseo se rompe, el panel deja de decir
// "ese nombre ya existe" y pasa a decir "HTTP 409" — o peor, enseña el código
// de error crudo. Por eso se prueba contra `request` de verdad, con `fetch`
// doblado, y no construyendo `ApiError` a mano: lo que importa es la cadena
// entera respuesta -> ApiError.
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from './api.js'

/** Dobla `fetch` con una respuesta controlada. */
function responderCon({ status, json, sinCuerpo = false }) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: sinCuerpo
      ? () => Promise.reject(new SyntaxError('Unexpected end of JSON input'))
      : () => Promise.resolve(json),
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ApiError, construido directamente', () => {
  it('parsea un detail con forma {code, params}', () => {
    const err = new ApiError(409, {
      code: 'err.session_exists',
      params: { name: 'sesion-1' },
    })

    expect(err.code).toBe('err.session_exists')
    expect(err.params).toEqual({ name: 'sesion-1' })
    expect(err.status).toBe(409)
  })

  it('cae al genérico cuando el detail es una cadena', () => {
    // El caso de un backend que devuelve texto plano: no hay código que
    // traducir, así que `code` se queda a null y el mensaje es ese texto.
    const err = new ApiError(400, 'algo ha ido mal')

    expect(err.code).toBeNull()
    expect(err.params).toEqual({})
    expect(err.message).toBe('algo ha ido mal')
  })

  it('conserva `technical` cuando viene', () => {
    // `technical` es el stderr de tmux y demás: texto SIN traducir que
    // acompaña al mensaje localizado. Perderlo deja al usuario sin el único
    // dato que explica qué pasó de verdad.
    const err = new ApiError(500, {
      code: 'err.tmux_unknown',
      technical: "can't find session: foo",
    })

    expect(err.technical).toBe("can't find session: foo")
  })

  it('deja `technical` a null cuando no viene', () => {
    expect(new ApiError(500, { code: 'err.x' }).technical).toBeNull()
  })
})

describe('request, de la respuesta HTTP al ApiError', () => {
  it('traduce un 401 a err.unauthorized', async () => {
    responderCon({ status: 401, json: {} })

    await expect(api.listSessions()).rejects.toMatchObject({
      status: 401,
      code: 'err.unauthorized',
    })
  })

  it('en un 401 gana el código que mande el backend', async () => {
    // El login devuelve 401 con `err.bad_credentials`. Cortar antes de mirar
    // el cuerpo dejaría ese caso con el genérico "no autorizado", que es
    // justo el mensaje equivocado en la pantalla de login.
    responderCon({ status: 401, json: { detail: { code: 'err.bad_credentials' } } })

    await expect(api.listSessions()).rejects.toMatchObject({
      code: 'err.bad_credentials',
    })
  })

  it('un cuerpo que no es JSON da err.http con el status en params', async () => {
    responderCon({ status: 502, sinCuerpo: true })

    await expect(api.listSessions()).rejects.toMatchObject({
      code: 'err.http',
      params: { status: 502 },
    })
  })

  it('un detail con otra forma NO se cuela como mensaje', async () => {
    // La lista de errores de validación de FastAPI (422) es un array de
    // objetos: no es texto presentable, así que tiene que quedarse el
    // genérico en vez de acabar pintado en la interfaz.
    responderCon({
      status: 422,
      json: { detail: [{ loc: ['body', 'name'], msg: 'field required' }] },
    })

    await expect(api.listSessions()).rejects.toMatchObject({
      code: 'err.http',
      params: { status: 422 },
    })
  })

  it('devuelve el cuerpo cuando la respuesta es correcta', async () => {
    // El control positivo: sin él, un `request` que lanzara siempre pasaría
    // todos los tests de arriba.
    responderCon({ status: 200, json: [{ name: 'sesion-1' }] })

    await expect(api.listSessions()).resolves.toEqual([{ name: 'sesion-1' }])
  })
})
