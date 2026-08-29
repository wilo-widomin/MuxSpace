// La pregunta por los huecos que la jornada ha descontado.
//
// El dato ya sale bien sin ella: el servidor descuenta solo los ratos sin
// ninguna señal. Esto es para corregir en caliente el hueco que SÍ era
// trabajo, y por eso lo que hay que vigilar no es que las horas cuadren, sino
// que la pregunta no se vuelva ruido: apagada por defecto, en una sola
// ventana, y una sola vez por hueco aunque haya cuatro ventanas abiertas.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PREF_PREGUNTAR, useGapQuestion } from './useGapQuestion.js'

const respuestas = {
  workGaps: vi.fn(),
  claimGap: vi.fn(),
}

vi.mock('./api.js', () => ({
  api: {
    workGaps: (...a) => respuestas.workGaps(...a),
    claimGap: (...a) => respuestas.claimGap(...a),
  },
  ApiError: class extends Error {},
}))

const HUECO = { start: 1000, end: 4600, seconds: 3600, claimed: false, answered: false }

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  localStorage.setItem(PREF_PREGUNTAR, '1')
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
  respuestas.workGaps.mockResolvedValue({ absence_minutes: 30, gaps: [HUECO] })
  respuestas.claimGap.mockResolvedValue({ start: 1000, end: 4600, worked: true })
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  localStorage.clear()
})

describe('el interruptor', () => {
  it('apagado, no pregunta nada ni consulta al servidor', async () => {
    localStorage.setItem(PREF_PREGUNTAR, '0')
    const { result } = renderHook(() => useGapQuestion(true))

    await act(async () => {})
    expect(result.current.hueco).toBe(null)
    expect(respuestas.workGaps).not.toHaveBeenCalled()
  })

  it('viene apagado si nadie lo ha encendido', () => {
    localStorage.clear()
    const { result } = renderHook(() => useGapQuestion(true))

    expect(result.current.preguntar).toBe(false)
  })

  it('«no preguntar más» lo apaga y lo recuerda', async () => {
    const { result } = renderHook(() => useGapQuestion(true))
    await waitFor(() => expect(result.current.hueco).not.toBe(null))

    act(() => {
      result.current.dejarDePreguntar()
    })

    expect(result.current.hueco).toBe(null)
    expect(localStorage.getItem(PREF_PREGUNTAR)).toBe('0')
  })

  it('sin sesión no se consulta nada', () => {
    renderHook(() => useGapQuestion(false))
    expect(respuestas.workGaps).not.toHaveBeenCalled()
  })
})

describe('la pregunta', () => {
  it('sale con el interruptor encendido y un hueco sin responder', async () => {
    const { result } = renderHook(() => useGapQuestion(true))

    await waitFor(() => expect(result.current.hueco).toEqual(HUECO))
  })

  it('pregunta solo la ventana que tiene el foco', async () => {
    // Con cuatro ventanas de MuxSpace abiertas, el mismo banner en todas es
    // la misma pregunta cuatro veces.
    document.hasFocus.mockReturnValue(false)
    const { result } = renderHook(() => useGapQuestion(true))

    await act(async () => {})
    expect(result.current.hueco).toBe(null)
  })

  it('un hueco ya respondido no se vuelve a preguntar', async () => {
    // La respuesta vive en el servidor: se contestó en otra ventana y esta ya
    // no tiene nada que preguntar.
    respuestas.workGaps.mockResolvedValue({
      absence_minutes: 30,
      gaps: [{ ...HUECO, answered: true }],
    })
    const { result } = renderHook(() => useGapQuestion(true))

    await act(async () => {})
    expect(result.current.hueco).toBe(null)
  })

  it('pregunta por el hueco más reciente, que es el que uno recuerda', async () => {
    const viejo = { ...HUECO, start: 100, end: 500, seconds: 400 }
    respuestas.workGaps.mockResolvedValue({ absence_minutes: 30, gaps: [viejo, HUECO] })
    const { result } = renderHook(() => useGapQuestion(true))

    await waitFor(() => expect(result.current.hueco).toEqual(HUECO))
  })
})

describe('la respuesta', () => {
  it('«trabajando» devuelve el hueco a la jornada', async () => {
    const { result } = renderHook(() => useGapQuestion(true))
    await waitFor(() => expect(result.current.hueco).not.toBe(null))

    await act(async () => {
      await result.current.responder(true)
    })

    expect(respuestas.claimGap).toHaveBeenCalledWith(1000 * 1000, 4600 * 1000, true)
    expect(result.current.hueco).toBe(null)
  })

  it('«fuera» también se guarda, para que no lo pregunte la ventana siguiente', async () => {
    const { result } = renderHook(() => useGapQuestion(true))
    await waitFor(() => expect(result.current.hueco).not.toBe(null))

    await act(async () => {
      await result.current.responder(false)
    })

    expect(respuestas.claimGap).toHaveBeenCalledWith(1000 * 1000, 4600 * 1000, false)
  })
})
