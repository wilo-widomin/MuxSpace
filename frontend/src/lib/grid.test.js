// Lo que el grid recibe de cada sesión.
//
// Este recorte se ha comido ya dos campos en producción —`project` (badges de
// enlaces que no salían) y `cwd` (tooltip sin el directorio)—, y en los dos
// casos el componente estaba bien y sus tests en verde: el campo se perdía
// aquí, entre la API y el tile. De ahí que lo que se comprueba abajo sea
// sobre todo QUÉ CAMPOS sobreviven.
import { describe, expect, it } from 'vitest'

import { sesionesDelGrid } from './grid.js'

const SIN_ASIGNAR = '__unassigned__'

const sesion = (extra) => ({
  name: 'MUXSPACE',
  windows: 1,
  attached: true,
  space: 'sp_1',
  project: 'p1',
  cwd: '~/proyectos/muxspace',
  command: 'claude',
  attention: null,
  ...extra,
})

describe('sesionesDelGrid', () => {
  it('el tile recibe el proyecto, el directorio y el programa', () => {
    const [s] = sesionesDelGrid([sesion()], 'sp_1', SIN_ASIGNAR, new Set(), [])

    expect(s).toEqual({
      name: 'MUXSPACE',
      project: 'p1',
      cwd: '~/proyectos/muxspace',
      command: 'claude',
    })
  })

  it('lo que la API no manda llega como null, no como undefined', () => {
    const [s] = sesionesDelGrid(
      [{ name: 'Terminal', space: 'sp_1' }],
      'sp_1',
      SIN_ASIGNAR,
      new Set(),
      [],
    )

    expect(s).toEqual({
      name: 'Terminal',
      project: null,
      cwd: null,
      command: null,
    })
  })

  it('solo salen las del espacio activo y las que no están ocultas', () => {
    const sesiones = [
      sesion({ name: 'aqui' }),
      sesion({ name: 'otra', space: 'sp_2' }),
      sesion({ name: 'cerrada' }),
      sesion({ name: 'suelta', space: null }),
    ]

    const nombres = sesionesDelGrid(
      sesiones,
      'sp_1',
      SIN_ASIGNAR,
      new Set(['cerrada']),
      [],
    ).map((s) => s.name)

    expect(nombres).toEqual(['aqui'])
  })

  it('«Sin asignar» es la ausencia de espacio, no un espacio más', () => {
    const sesiones = [sesion({ name: 'suelta', space: null }), sesion({ name: 'aqui' })]

    const nombres = sesionesDelGrid(
      sesiones,
      SIN_ASIGNAR,
      SIN_ASIGNAR,
      new Set(),
      [],
    ).map((s) => s.name)

    expect(nombres).toEqual(['suelta'])
  })

  it('manda el orden manual y las nuevas van al final, alfabéticamente', () => {
    const sesiones = ['zeta', 'alfa', 'tercera', 'primera'].map((name) =>
      sesion({ name }),
    )

    const nombres = sesionesDelGrid(sesiones, 'sp_1', SIN_ASIGNAR, new Set(), [
      'primera',
      'tercera',
    ]).map((s) => s.name)

    expect(nombres).toEqual(['primera', 'tercera', 'alfa', 'zeta'])
  })
})
