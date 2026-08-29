// El botón de pausa del registro de tiempo.
//
// En el modo 'workday' la jornada cuenta entera y las ausencias largas las
// descuenta el servidor solo, sin preguntar. Este botón cubre la ausencia
// corta que uno decide declarar, y su forma de mentir es enseñar un estado
// que no es el del servidor: se pulsa «me voy» en el portátil y se vuelve
// desde la tableta, y la pausa tiene que ser la misma.
//
// El reloj se controla con temporizadores falsos: el sondeo es de un minuto.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkPause } from './useWorkPause.js'

const respuestas = {
  workPauses: vi.fn(),
  workPause: vi.fn(),
  workResume: vi.fn(),
}

vi.mock('./api.js', () => ({
  api: {
    workPauses: (...a) => respuestas.workPauses(...a),
    workPause: (...a) => respuestas.workPause(...a),
    workResume: (...a) => respuestas.workResume(...a),
  },
  ApiError: class extends Error {},
}))

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  respuestas.workPauses.mockResolvedValue({
    mode: 'workday',
    pauses: [],
    last_slot: Math.floor(Date.now() / 1000),
  })
  respuestas.workPause.mockResolvedValue({ start: 0 })
  respuestas.workResume.mockResolvedValue({ pause: null })
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe('el botón de pausa', () => {
  it('refleja el modo y la pausa que dice el servidor', async () => {
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [{ start: 1, end: null, open: true }],
      last_slot: Math.floor(Date.now() / 1000),
    })
    const { result } = renderHook(() => useWorkPause(true))

    await waitFor(() => expect(result.current.pausado).toBe(true))
    expect(result.current.modo).toBe('workday')
  })

  it('la pausa vive en el servidor, no en la pestaña', async () => {
    // Es lo que permite irse del portátil y volver desde la tableta con la
    // misma pausa abierta.
    const { result } = renderHook(() => useWorkPause(true))
    await waitFor(() => expect(respuestas.workPauses).toHaveBeenCalled())

    await act(async () => {
      await result.current.alternarPausa()
    })

    expect(respuestas.workPause).toHaveBeenCalled()
    expect(result.current.pausado).toBe(true)
  })

  it('estando en pausa, el botón reanuda', async () => {
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [{ start: 1, end: null, open: true }],
      last_slot: Math.floor(Date.now() / 1000),
    })
    const { result } = renderHook(() => useWorkPause(true))
    await waitFor(() => expect(result.current.pausado).toBe(true))

    await act(async () => {
      await result.current.alternarPausa()
    })

    expect(respuestas.workResume).toHaveBeenCalled()
    expect(respuestas.workPause).not.toHaveBeenCalled()
  })

  it('sin sesión no se consulta nada', () => {
    renderHook(() => useWorkPause(false))
    expect(respuestas.workPauses).not.toHaveBeenCalled()
  })
})
