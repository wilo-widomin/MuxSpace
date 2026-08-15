import { describe, it, expect } from 'vitest'
import { initialSpace, spaceKeyOf, LEGACY_ALL_SPACES, UNASSIGNED } from './spaces.js'

// Con qué espacio arranca una pestaña. El fallo que esto fija: `?space=` se
// quedaba en la URL para siempre, así que CADA recarga volvía a imponer el
// espacio con el que se abrió la pestaña días atrás y sacaba al usuario del
// que estaba usando, en silencio. Se arregla borrando el parámetro tras
// consumirlo (App.jsx); aquí se fija la otra mitad: sin parámetro manda lo
// guardado.
describe('initialSpace', () => {
  it('obedece el ?space= cuando llega (orden de apertura)', () => {
    expect(initialSpace('?space=abc123', 'otro')).toBe('abc123')
  })

  it('sin parámetro manda lo que la pestaña recordaba', () => {
    expect(initialSpace('', 'mi-espacio')).toBe('mi-espacio')
  })

  it('sin parámetro ni recuerdo, «sin asignar»', () => {
    expect(initialSpace('', null)).toBe(UNASSIGNED)
  })

  it('degrada la vista «todas» que ya no existe', () => {
    expect(initialSpace('', LEGACY_ALL_SPACES)).toBe(UNASSIGNED)
  })
})

describe('spaceKeyOf', () => {
  it('una sesión sin espacio cuenta como «sin asignar»', () => {
    expect(spaceKeyOf({ name: 'x', space: null })).toBe(UNASSIGNED)
    expect(spaceKeyOf({ name: 'x', space: 'abc' })).toBe('abc')
  })
})
