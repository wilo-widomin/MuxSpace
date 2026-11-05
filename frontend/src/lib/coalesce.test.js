import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { coalesce } from './coalesce.js'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('coalesce', () => {
  it('una ráfaga de avisos es una sola recarga', async () => {
    const recargar = vi.fn(async () => {})
    const avisar = coalesce(recargar, 100)

    avisar()
    avisar()
    avisar()
    await vi.advanceTimersByTimeAsync(100)

    expect(recargar).toHaveBeenCalledTimes(1)
  })

  it('una ráfaga larga no aplaza la recarga para siempre', async () => {
    const recargar = vi.fn(async () => {})
    const avisar = coalesce(recargar, 100)

    avisar()
    await vi.advanceTimersByTimeAsync(60)
    avisar()
    await vi.advanceTimersByTimeAsync(40)

    expect(recargar).toHaveBeenCalledTimes(1)
  })

  it('lo que llega con una recarga en marcha provoca una sola más al terminar', async () => {
    const terminar = []
    const recargar = vi.fn(() => new Promise((resolve) => terminar.push(resolve)))
    const avisar = coalesce(recargar, 100)

    avisar()
    await vi.advanceTimersByTimeAsync(100)
    avisar()
    avisar()
    await vi.advanceTimersByTimeAsync(500)
    expect(recargar).toHaveBeenCalledTimes(1)

    terminar[0]()
    await vi.advanceTimersByTimeAsync(100)
    expect(recargar).toHaveBeenCalledTimes(2)

    terminar[1]()
    await vi.advanceTimersByTimeAsync(500)
    expect(recargar).toHaveBeenCalledTimes(2)
  })

  it('un fallo al recargar no deja de atender los avisos siguientes', async () => {
    const recargar = vi.fn(async () => {}).mockRejectedValueOnce(new Error('caído'))
    const avisar = coalesce(async () => {
      await recargar().catch(() => {})
    }, 100)

    avisar()
    await vi.advanceTimersByTimeAsync(100)
    avisar()
    await vi.advanceTimersByTimeAsync(100)

    expect(recargar).toHaveBeenCalledTimes(2)
  })

  it('cancelar deja sin efecto lo que estaba por venir', async () => {
    const recargar = vi.fn(async () => {})
    const avisar = coalesce(recargar, 100)

    avisar()
    avisar.cancelar()
    await vi.advanceTimersByTimeAsync(500)

    expect(recargar).not.toHaveBeenCalled()
  })
})
