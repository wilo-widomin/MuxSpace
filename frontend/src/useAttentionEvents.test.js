// El bus de eventos: quien se reconecta tiene que ponerse al día, porque el bus
// no guarda nada y lo que pasó con la conexión caída no se vuelve a mandar.
import { cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAttentionEvents } from './useAttentionEvents.js'

class WebSocketFalso {
  static abiertos = []

  constructor(url) {
    this.url = url
    WebSocketFalso.abiertos.push(this)
  }

  abrir() {
    this.onopen?.()
  }

  mandar(mensaje) {
    this.onmessage?.({ data: JSON.stringify(mensaje) })
  }

  cerrar() {
    this.onclose?.()
  }

  close() {}
}

beforeEach(() => {
  vi.useFakeTimers()
  WebSocketFalso.abiertos = []
  vi.stubGlobal('WebSocket', WebSocketFalso)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const ultimo = () => WebSocketFalso.abiertos.at(-1)

describe('useAttentionEvents', () => {
  it('la primera conexión no recarga: de eso ya se ocupa la carga inicial', () => {
    const alReconectar = vi.fn()
    renderHook(() => useAttentionEvents(() => {}, true, alReconectar))

    ultimo().abrir()

    expect(alReconectar).not.toHaveBeenCalled()
  })

  it('al volver tras un corte se pide ponerse al día, una vez', async () => {
    const alReconectar = vi.fn()
    renderHook(() => useAttentionEvents(() => {}, true, alReconectar))
    ultimo().abrir()

    ultimo().cerrar()
    await vi.advanceTimersByTimeAsync(500)
    ultimo().abrir()

    expect(WebSocketFalso.abiertos).toHaveLength(2)
    expect(alReconectar).toHaveBeenCalledTimes(1)
  })

  it('si la primera conexión falló, la que entra después también se pone al día', async () => {
    const alReconectar = vi.fn()
    renderHook(() => useAttentionEvents(() => {}, true, alReconectar))

    ultimo().cerrar()
    await vi.advanceTimersByTimeAsync(500)
    ultimo().abrir()

    expect(alReconectar).toHaveBeenCalledTimes(1)
  })

  it('ponerse al día no provoca ninguna conexión nueva', async () => {
    const alReconectar = vi.fn()
    renderHook(() => useAttentionEvents(() => {}, true, alReconectar))
    ultimo().abrir()
    ultimo().cerrar()
    await vi.advanceTimersByTimeAsync(500)
    ultimo().abrir()

    await vi.advanceTimersByTimeAsync(60_000)

    expect(WebSocketFalso.abiertos).toHaveLength(2)
    expect(alReconectar).toHaveBeenCalledTimes(1)
  })

  it('entrega los eventos y se calla los latidos', () => {
    const alEvento = vi.fn()
    renderHook(() => useAttentionEvents(alEvento))
    ultimo().abrir()

    ultimo().mandar({ type: 'ping' })
    ultimo().mandar({ type: 'projects-changed' })

    expect(alEvento.mock.calls).toEqual([[{ type: 'projects-changed' }]])
  })
})
