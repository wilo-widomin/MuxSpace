import { describe, it, expect } from 'vitest'
import { porNombre } from './orden.js'

// El orden de los catálogos (comandos, proyectos, espacios). Comparar con `<`
// funciona hasta el día que aparece un acento o un número de dos cifras, y
// entonces la lista queda "casi" ordenada, que es peor que desordenada porque
// nadie lo mira dos veces.
describe('porNombre', () => {
  it('ordena alfabéticamente sin distinguir mayúsculas', () => {
    const lista = [{ t: 'zeta' }, { t: 'Alfa' }, { t: 'beta' }]
    expect(porNombre(lista, 't').map((x) => x.t)).toEqual(['Alfa', 'beta', 'zeta'])
  })

  it('coloca los acentos donde los espera una persona', () => {
    const lista = [{ t: 'Zaragoza' }, { t: 'Ávila' }, { t: 'Barcelona' }]
    expect(porNombre(lista, 't').map((x) => x.t)).toEqual([
      'Ávila',
      'Barcelona',
      'Zaragoza',
    ])
  })

  it('ordena los números como números: sesion-2 antes que sesion-10', () => {
    const lista = [{ t: 'sesion-10' }, { t: 'sesion-2' }]
    expect(porNombre(lista, 't').map((x) => x.t)).toEqual(['sesion-2', 'sesion-10'])
  })

  it('no toca la lista original ni se atraganta con un campo vacío', () => {
    const lista = [{ t: 'b' }, {}, { t: 'a' }]
    const ordenada = porNombre(lista, 't')
    expect(ordenada.map((x) => x.t)).toEqual([undefined, 'a', 'b'])
    expect(lista.map((x) => x.t)).toEqual(['b', undefined, 'a'])
  })
})
