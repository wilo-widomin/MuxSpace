import { describe, expect, it } from 'vitest'

import { needsLaunch } from './sessions.js'

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
