import { describe, it, expect } from 'vitest'
import {
  ACTIVITY_EVENTS,
  IDLE_TIMEOUT_MS,
  MANUAL_MAX_MS,
  formatDuration,
  isWorking,
  manualExpired,
} from './worklog.js'

// La regla que decide si una ranura cuenta como trabajo. Su forma de fallar no
// es reventar: es dar un total creíble y falso. Los tres casos que lo
// invertirían están aquí.
describe('isWorking', () => {
  const AHORA = 1_000_000

  it('cuenta con foco y entrada reciente', () => {
    expect(isWorking({ hasFocus: true, lastInput: AHORA - 1000 }, AHORA)).toBe(true)
  })

  it('NO cuenta sin foco, aunque se acabe de teclear', () => {
    // El caso de las dos pestañas: la que no miras no puede acumular.
    expect(isWorking({ hasFocus: false, lastInput: AHORA }, AHORA)).toBe(false)
  })

  it('NO cuenta con foco pero sin entrada: irse a comer no es trabajar', () => {
    expect(
      isWorking({ hasFocus: true, lastInput: AHORA - IDLE_TIMEOUT_MS - 1 }, AHORA),
    ).toBe(false)
  })

  it('solo entrada del usuario abre el reloj', () => {
    // La lista es el contrato del módulo: cinco eventos del usuario y ninguna
    // señal de salida. Si alguien engancha aquí el tráfico del PTY, el
    // registro pasaría a medir justo las horas que NO se trabaja —el agente
    // escupiendo texto con el usuario en otra pestaña— y el dato quedaría
    // invertido sin que nada fallara. Por eso la lista se fija por escrito.
    expect(ACTIVITY_EVENTS).toEqual([
      'keydown',
      'mousemove',
      'click',
      'scroll',
      'touchstart',
    ])
  })

  it('el modo manual cuenta sin entrada, pero solo un rato', () => {
    const parado = { hasFocus: true, lastInput: AHORA - IDLE_TIMEOUT_MS - 1 }
    expect(
      isWorking({ ...parado, manual: true, manualSince: AHORA - 60_000 }, AHORA),
    ).toBe(true)
    // Caducado: un interruptor olvidado no puede apuntarse la noche entera.
    expect(
      isWorking({ ...parado, manual: true, manualSince: AHORA - MANUAL_MAX_MS }, AHORA),
    ).toBe(false)
  })

  it('el modo manual tampoco cuenta sin foco', () => {
    expect(
      isWorking(
        { hasFocus: false, lastInput: 0, manual: true, manualSince: AHORA },
        AHORA,
      ),
    ).toBe(false)
  })
})

describe('manualExpired', () => {
  it('avisa cuando el forzado ya no vale, para poder apagar el indicador', () => {
    expect(manualExpired({ manual: true, manualSince: 0 }, MANUAL_MAX_MS)).toBe(true)
    expect(manualExpired({ manual: true, manualSince: 0 }, 1000)).toBe(false)
    expect(manualExpired({ manual: false, manualSince: 0 }, MANUAL_MAX_MS)).toBe(false)
  })
})

describe('formatDuration', () => {
  it('redondea a minutos y no produce «2 h 60 min»', () => {
    expect(formatDuration(0)).toBe('—')
    expect(formatDuration(90)).toBe('2 min')
    expect(formatDuration(3600)).toBe('1 h')
    expect(formatDuration(12_300)).toBe('3 h 25 min')
    expect(formatDuration(7190)).toBe('2 h')
  })
})
