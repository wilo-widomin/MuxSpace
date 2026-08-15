import { describe, it, expect } from 'vitest'
import {
  ACTIVITY_EVENTS,
  IDLE_TIMEOUT_MS,
  MANUAL_MAX_MS,
  formatDate,
  formatDuration,
  formatDurationExact,
  formatTime,
  isWorking,
  manualExpired,
} from './worklog.js'

// La regla que decide si una ranura cuenta como trabajo. Su forma de fallar no
// es reventar: es dar un total creíble y falso. Los tres casos que lo
// invertirían están aquí.
describe('isWorking', () => {
  const AHORA = 1_000_000

  it('cuenta como MEDIDO con foco y entrada reciente', () => {
    expect(isWorking({ hasFocus: true, lastInput: AHORA - 1000 }, AHORA)).toBe('auto')
  })

  it('NO cuenta sin foco si no lo has declarado', () => {
    // El caso de las dos pestañas: la que no miras no acumula por su cuenta.
    expect(isWorking({ hasFocus: false, lastInput: AHORA }, AHORA)).toBe(null)
  })

  it('NO cuenta con foco pero sin entrada: irse a comer no es trabajar', () => {
    expect(
      isWorking({ hasFocus: true, lastInput: AHORA - IDLE_TIMEOUT_MS - 1 }, AHORA),
    ).toBe(null)
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

  it('el modo declarado cuenta SIN foco: para eso existe', () => {
    // Es el caso de probar en otra pestaña la app que estás construyendo.
    // Exigir foco aquí sería exigir que estés donde precisamente no estás.
    expect(
      isWorking(
        { hasFocus: false, lastInput: 0, manual: true, manualSince: AHORA - 60_000 },
        AHORA,
      ),
    ).toBe('manual')
  })

  it('el modo declarado caduca: un interruptor olvidado no cuenta la noche', () => {
    expect(
      isWorking(
        {
          hasFocus: false,
          lastInput: 0,
          manual: true,
          manualSince: AHORA - MANUAL_MAX_MS,
        },
        AHORA,
      ),
    ).toBe(null)
  })

  it('y se apaga si el sistema dice que no estás delante', () => {
    // Pantalla bloqueada o sin actividad en la máquina: da igual lo que
    // hayas declarado, ahí no hay nadie trabajando.
    expect(
      isWorking(
        {
          hasFocus: false,
          lastInput: 0,
          manual: true,
          manualSince: AHORA,
          userAway: true,
        },
        AHORA,
      ),
    ).toBe(null)
  })

  it('con foco y entrada, lo medido manda sobre lo declarado', () => {
    // Si estás aquí trabajando, esa ranura es medida aunque el interruptor
    // esté encendido: no tiene sentido marcarla como declarada.
    expect(
      isWorking(
        { hasFocus: true, lastInput: AHORA, manual: true, manualSince: AHORA },
        AHORA,
      ),
    ).toBe('auto')
  })
})

describe('manualExpired', () => {
  it('avisa cuando el forzado ya no vale, para poder apagar el indicador', () => {
    expect(manualExpired({ manual: true, manualSince: 0 }, MANUAL_MAX_MS)).toBe(true)
    expect(manualExpired({ manual: true, manualSince: 0 }, 1000)).toBe(false)
    expect(manualExpired({ manual: false, manualSince: 0 }, MANUAL_MAX_MS)).toBe(false)
  })
})

describe('formatDate', () => {
  it('siempre dd/mm/aaaa, no el formato del navegador', () => {
    // En inglés, `toLocaleDateString` daría 04/03 para el 3 de abril. Una
    // tabla en la que 03/04 significa una cosa u otra según quién la mire no
    // es una tabla de fechas.
    expect(formatDate('2026-04-03')).toBe('03/04/2026')
  })

  it('un día del servidor no se corre al día anterior', () => {
    // 'aaaa-mm-dd' pasado por `new Date()` se interpreta como UTC, y en una
    // zona negativa saldría el día de antes. Por eso se reordena la cadena.
    expect(formatDate('2026-01-01')).toBe('01/01/2026')
  })

  it('también acepta epoch en segundos y Date', () => {
    const fecha = new Date(2026, 7, 15, 9, 30)
    expect(formatDate(fecha)).toBe('15/08/2026')
    expect(formatDate(Math.floor(fecha.getTime() / 1000))).toBe('15/08/2026')
  })
})

describe('formatTime', () => {
  it('hora local en 24 h con dos dígitos', () => {
    const fecha = new Date(2026, 7, 15, 9, 5)
    expect(formatTime(Math.floor(fecha.getTime() / 1000))).toBe('09:05')
  })
})

describe('formatDurationExact', () => {
  it('no redondea a minutos: once tramos de 30 s suman 11 min, no 15', () => {
    // El fallo que fija: cada fila redondeada a "1 min" hacía que la lista
    // pareciera sumar más que su propio total.
    expect(formatDurationExact(30)).toBe('30 s')
    expect(formatDurationExact(90)).toBe('1 min 30 s')
    const once = Array.from({ length: 11 }, () => 60).reduce((a, b) => a + b, 0)
    expect(formatDurationExact(once)).toBe('11 min')
  })

  it('a partir de una hora, los segundos ya no aportan nada', () => {
    expect(formatDurationExact(3600)).toBe('1 h')
    expect(formatDurationExact(12_345)).toBe('3 h 25 min')
    expect(formatDurationExact(0)).toBe('—')
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
