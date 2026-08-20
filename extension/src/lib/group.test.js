// Abrir un proyecto dos veces tiene que dar el mismo grupo, no dos.
import { describe, expect, it } from 'vitest'

import { groupColor, missingUrls, plannedUrls, sameTabKey } from './group.js'

const PANEL = 'https://panel.interno'

const PROYECTO = {
  space: 'sp1',
  links: [
    { url: 'https://github.com/willy/muxspace' },
    { url: 'https://docs.interno/muxspace' },
  ],
}

describe('plannedUrls', () => {
  it('el panel va el primero y los enlaces detrás, en su orden', () => {
    expect(plannedUrls(PROYECTO, `${PANEL}/?space=sp1`)).toEqual([
      `${PANEL}/?space=sp1`,
      'https://github.com/willy/muxspace',
      'https://docs.interno/muxspace',
    ])
  })

  it('un proyecto sin enlaces abre solo el panel', () => {
    expect(plannedUrls({ space: 'sp1', links: [] }, `${PANEL}/?space=sp1`)).toEqual([
      `${PANEL}/?space=sp1`,
    ])
  })

  it('un enlace vacío no abre una pestaña en blanco', () => {
    const proyecto = { space: null, links: [{ url: '  ' }, { url: 'https://ok.example' }] }
    expect(plannedUrls(proyecto, `${PANEL}/`)).toEqual([
      `${PANEL}/`,
      'https://ok.example',
    ])
  })
})

describe('sameTabKey', () => {
  it('la barra final no hace dos pestañas de una', () => {
    expect(sameTabKey('https://github.com/foo')).toBe(sameTabKey('https://github.com/foo/'))
  })

  it('pero la query sí distingue: son páginas distintas', () => {
    expect(sameTabKey('https://foo.example/?a=1')).not.toBe(
      sameTabKey('https://foo.example/?a=2'),
    )
  })
})

describe('missingUrls', () => {
  const planned = plannedUrls(PROYECTO, `${PANEL}/?space=sp1`)

  it('con el grupo vacío hay que abrirlo todo', () => {
    expect(missingUrls(planned, [], PANEL)).toEqual(planned)
  })

  it('con el grupo completo no se abre nada', () => {
    expect(missingUrls(planned, planned, PANEL)).toEqual([])
  })

  it('solo abre el enlace que falta', () => {
    const abiertas = [`${PANEL}/?space=sp1`, 'https://github.com/willy/muxspace']
    expect(missingUrls(planned, abiertas, PANEL)).toEqual([
      'https://docs.interno/muxspace',
    ])
  })

  it('no duplica el panel aunque esté mirando otro espacio', () => {
    // El usuario cambió de espacio a mano en esa pestaña. Volver a abrir el
    // proyecto no puede plantarle un segundo panel al lado.
    const abiertas = [`${PANEL}/?space=OTRO`, 'https://github.com/willy/muxspace']
    expect(missingUrls(planned, abiertas, PANEL)).toEqual([
      'https://docs.interno/muxspace',
    ])
  })

  it('una URL ilegible entre las abiertas no rompe el cálculo', () => {
    expect(missingUrls(planned, ['about:blank'], PANEL)).toEqual(planned)
  })
})

describe('groupColor', () => {
  it('el mismo proyecto da siempre el mismo color', () => {
    expect(groupColor('abc123')).toBe(groupColor('abc123'))
  })

  it('es uno de los que acepta Chrome', () => {
    const validos = [
      'blue',
      'cyan',
      'green',
      'grey',
      'orange',
      'pink',
      'purple',
      'red',
      'yellow',
    ]
    for (const id of ['a', 'bb', 'ccc', '0f9e', 'muxspace']) {
      expect(validos).toContain(groupColor(id))
    }
  })
})
