// Las pausas del registro de tiempo.
//
// En el modo 'workday' la jornada cuenta entera y lo que se declara es la
// AUSENCIA. Eso invierte la forma de fallar: el modo medido pecaba de corto,
// este peca de largo. Sus dos maneras de mentir son marcar una pausa que no
// existió (resta trabajo real) y no marcar la que sí (suma ausencia como
// trabajo), y las dos pasan por este hook.
//
// El reloj se controla con temporizadores falsos: un test que espera media
// hora para ver saltar la pregunta no se ejecuta nunca.
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkPause } from './useWorkPause.js'

const respuestas = {
  workPauses: vi.fn(),
  workPause: vi.fn(),
  workResume: vi.fn(),
  markPause: vi.fn(),
}

vi.mock('./api.js', () => ({
  api: {
    workPauses: (...a) => respuestas.workPauses(...a),
    workPause: (...a) => respuestas.workPause(...a),
    workResume: (...a) => respuestas.workResume(...a),
    markPause: (...a) => respuestas.markPause(...a),
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
  respuestas.markPause.mockResolvedValue({ start: 0, end: 0 })
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

describe('la pregunta al volver de un hueco largo', () => {
  // El hueco se mide por la FALTA DE LATIDOS, no por un salto del reloj: irse
  // a comer dejando el panel abierto no mueve ningún reloj, y es justo la
  // ausencia que hay que cazar.
  const haceMinutos = (m) => Math.floor((Date.now() - m * 60_000) / 1000)

  it('no pregunta por un hueco corto', async () => {
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [],
      last_slot: haceMinutos(5),
    })
    const { result } = renderHook(() => useWorkPause(true))

    await waitFor(() => expect(respuestas.workPauses).toHaveBeenCalled())
    expect(result.current.pregunta).toBeNull()
  })

  it('pregunta tras media hora sin un solo latido', async () => {
    const ultimo = haceMinutos(45)
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [],
      last_slot: ultimo,
    })
    const { result } = renderHook(() => useWorkPause(true))

    await waitFor(() => expect(result.current.pregunta).not.toBeNull())
    expect(result.current.pregunta.desde).toBe(ultimo * 1000)
  })

  it('no pregunta por un hueco que ya tiene su pausa marcada', async () => {
    // Sin esto, cada pausa contestada se volvería a preguntar en el siguiente
    // sondeo hasta que llegara un latido nuevo.
    const ultimo = haceMinutos(45)
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [{ start: ultimo, end: haceMinutos(1), open: false }],
      last_slot: ultimo,
    })
    const { result } = renderHook(() => useWorkPause(true))

    await waitFor(() => expect(respuestas.workPauses).toHaveBeenCalled())
    expect(result.current.pregunta).toBeNull()
  })

  it('responder «fuera» marca la pausa con las horas reales del hueco', async () => {
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [],
      last_slot: haceMinutos(45),
    })
    const { result } = renderHook(() => useWorkPause(true))
    await waitFor(() => expect(result.current.pregunta).not.toBeNull())
    const hueco = result.current.pregunta

    await act(async () => {
      await result.current.responder(true)
    })

    expect(respuestas.markPause).toHaveBeenCalledWith(hueco.desde, hueco.hasta)
    expect(result.current.pregunta).toBeNull()
  })

  it('responder «trabajando» no marca ninguna pausa', async () => {
    // El caso que más pesa: medido sobre un día real, un hueco de 60 minutos
    // sin una sola señal era trabajo entero. Si esto marcara pausa «por si
    // acaso», el modo perdería justo lo que vino a arreglar.
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [],
      last_slot: haceMinutos(45),
    })
    const { result } = renderHook(() => useWorkPause(true))
    await waitFor(() => expect(result.current.pregunta).not.toBeNull())

    await act(async () => {
      await result.current.responder(false)
    })

    expect(respuestas.markPause).not.toHaveBeenCalled()
    expect(result.current.pregunta).toBeNull()
  })

  it('no insiste con el mismo hueco en el sondeo siguiente', async () => {
    // Una pregunta que reaparece se contesta sin leerla, y una respuesta
    // pulsada por quitarla de en medio es peor que no preguntar.
    respuestas.workPauses.mockResolvedValue({
      mode: 'workday',
      pauses: [],
      last_slot: haceMinutos(45),
    })
    const { result } = renderHook(() => useWorkPause(true))
    await waitFor(() => expect(result.current.pregunta).not.toBeNull())
    await act(async () => {
      await result.current.responder(false)
    })

    await act(async () => {
      vi.advanceTimersByTime(61_000)
    })
    await waitFor(() => expect(respuestas.workPauses).toHaveBeenCalledTimes(2))

    expect(result.current.pregunta).toBeNull()
  })
})
