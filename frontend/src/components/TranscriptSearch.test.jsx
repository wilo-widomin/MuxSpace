import { describe, it, expect } from 'vitest'
import { trocear } from './TranscriptSearch.jsx'

// `trocear` es el corazón del buscador de la conversación: parte cada bloque
// en fragmentos y numera las coincidencias. Si esa numeración se descuadra,
// el contador dice «3 de 17» y la flecha lleva a otro sitio — un fallo que
// desde fuera parece que la búsqueda "va mal" sin más.
describe('trocear', () => {
  it('sin aguja devuelve el texto intacto y ninguna coincidencia', () => {
    const { partes, total } = trocear('hola mundo', '', 0)
    expect(total).toBe(0)
    expect(partes).toEqual([{ texto: 'hola mundo', coincidencia: false }])
  })

  it('encuentra sin distinguir mayúsculas y conserva el texto original', () => {
    const { partes, total } = trocear('MiAguja y miaguja', 'MIAGUJA', 0)
    expect(total).toBe(2)
    // Lo resaltado debe verse tal cual estaba escrito, no en la caja de la
    // búsqueda: si no, el modal "corrige" el contenido al buscarlo.
    expect(partes.filter((p) => p.coincidencia).map((p) => p.texto)).toEqual([
      'MiAguja',
      'miaguja',
    ])
    expect(partes.map((p) => p.texto).join('')).toBe('MiAguja y miaguja')
  })

  it('numera las coincidencias a partir del índice global del bloque', () => {
    const { partes } = trocear('aXaXa', 'X', 7)
    expect(partes.filter((p) => p.coincidencia).map((p) => p.indice)).toEqual([7, 8])
  })

  it('no se atasca cuando la coincidencia está al principio y al final', () => {
    const { partes, total } = trocear('XaX', 'X', 0)
    expect(total).toBe(2)
    expect(partes.map((p) => p.texto).join('')).toBe('XaX')
  })
})
