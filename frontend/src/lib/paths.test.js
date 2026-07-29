// `quotePath` decide si una ruta se puede pegar tal cual en una terminal.
//
// Es la función con más riesgo por línea de todo el frontend: el panel copia
// su salida al portapapeles para que el usuario la pegue en una shell. Un
// fallo aquí no es un texto feo, es una ruta que el shell interpreta.
import { describe, expect, it } from 'vitest'

import { quotePath } from './paths.js'

describe('quotePath', () => {
  it('deja sin comillas una ruta que el shell no tocaría', () => {
    // Sin esto, TODO iría entrecomillado y el test de abajo pasaría igual.
    expect(quotePath('/home/willy/proyecto')).toBe('/home/willy/proyecto')
    expect(quotePath('/x/con-guion_y.punto')).toBe('/x/con-guion_y.punto')
  })

  it('entrecomilla una ruta con espacios', () => {
    expect(quotePath('/tmp/mi carpeta/foto.png')).toBe('"/tmp/mi carpeta/foto.png"')
  })

  it.each([
    ['comilla doble', '/x/con"comilla', '"/x/con\\"comilla"'],
    ['dólar', '/x/con$HOME', '"/x/con\\$HOME"'],
    ['backtick', '/x/con`id`', '"/x/con\\`id\\`"'],
    ['barra invertida', '/x/con\\barra', '"/x/con\\\\barra"'],
  ])(
    'escapa el %s, que sigue siendo especial dentro de comillas',
    (_, entrada, esperado) => {
      expect(quotePath(entrada)).toBe(esperado)
    },
  )

  it('NO entrecomilla la virgulilla, para que el shell la expanda', () => {
    // Es el caso que parece un descuido y no lo es: `cd "~/x"` busca un
    // directorio llamado literalmente `~`. Lo mismo que documenta
    // `_quote_path` en el backend.
    expect(quotePath('~')).toBe('~')
    expect(quotePath('~/proyectos/muxspace')).toBe('~/proyectos/muxspace')
  })

  it('devuelve la cadena vacía tal cual', () => {
    // Comportamiento definido a propósito: no hay ruta que entrecomillar.
    expect(quotePath('')).toBe('')
  })

  it('entrecomilla los metacaracteres que ejecutarían algo', () => {
    // La propiedad de fondo: nada de lo que salga de aquí puede ejecutarse al
    // pegarlo. `$(...)` y `;` van dentro de comillas, y el `$` además
    // escapado.
    expect(quotePath('/x/$(id)')).toBe('"/x/\\$(id)"')
    expect(quotePath('/x/a;rm -rf b')).toBe('"/x/a;rm -rf b"')
    expect(quotePath('/x/a && b')).toBe('"/x/a && b"')
  })
})
