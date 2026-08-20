import { describe, expect, it } from 'vitest'

import { needsLaunch, sessionsToAdopt } from './sessions.js'

describe('needsLaunch', () => {
  it('sin ninguna sesión del proyecto, hay que lanzarlo', () => {
    expect(needsLaunch([], 'p1')).toBe(true)
  })

  it('con una sesión suya viva, no', () => {
    // El control que evita el muro de terminales al reabrir el grupo.
    expect(needsLaunch([{ name: 'Panel', project: 'p1' }], 'p1')).toBe(false)
  })

  it('las sesiones de OTRO proyecto no cuentan', () => {
    expect(needsLaunch([{ name: 'Otra', project: 'p2' }], 'p1')).toBe(true)
  })

  it('una sesión suelta (sin proyecto) tampoco cuenta', () => {
    expect(needsLaunch([{ name: 'suelta', project: null }], 'p1')).toBe(true)
  })

  it('una respuesta que no es una lista no hace lanzar a ciegas', () => {
    expect(needsLaunch(null, 'p1')).toBe(true)
    expect(needsLaunch(undefined, 'p1')).toBe(true)
  })

  it('sin proyecto no hay nada que lanzar', () => {
    expect(needsLaunch([], '')).toBe(false)
  })
})

describe('sessionsToAdopt', () => {
  it('trae al espacio del proyecto las suyas que están fuera', () => {
    const sesiones = [
      { name: 'MVP-LAB', project: 'p1', space: null },
      { name: 'MVP-LAB (2)', project: 'p1', space: 'otro' },
    ]
    expect(sessionsToAdopt(sesiones, 'p1', 'sp1')).toEqual(['MVP-LAB', 'MVP-LAB (2)'])
  })

  it('no toca las que ya están en su espacio', () => {
    const sesiones = [{ name: 'MVP-LAB', project: 'p1', space: 'sp1' }]
    expect(sessionsToAdopt(sesiones, 'p1', 'sp1')).toEqual([])
  })

  it('no arrastra las de otro proyecto ni las sueltas', () => {
    // El control que importa: mover la sesión que alguien creó a mano sería
    // moverle su trabajo de sitio sin avisar.
    const sesiones = [
      { name: 'otra', project: 'p2', space: null },
      { name: 'suelta', project: null, space: null },
    ]
    expect(sessionsToAdopt(sesiones, 'p1', 'sp1')).toEqual([])
  })

  it('sin espacio no hay a dónde traerlas', () => {
    const sesiones = [{ name: 'MVP-LAB', project: 'p1', space: null }]
    expect(sessionsToAdopt(sesiones, 'p1', null)).toEqual([])
  })

  it('una respuesta que no es una lista no rompe', () => {
    expect(sessionsToAdopt(null, 'p1', 'sp1')).toEqual([])
  })
})
