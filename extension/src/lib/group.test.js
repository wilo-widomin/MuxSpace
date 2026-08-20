// Abrir un proyecto dos veces tiene que dar el mismo grupo, no dos.
import { describe, expect, it } from 'vitest'

import { groupColor, plannedUrls, reconcileGroup, sameTabKey } from './group.js'

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

describe('reconcileGroup', () => {
  const planned = plannedUrls(PROYECTO, `${PANEL}/?space=sp1`)
  const pestana = (id, url) => ({ id, url })

  it('con el grupo vacío hay que abrirlo todo y no hay nada que llevar', () => {
    expect(reconcileGroup(planned, [], PANEL)).toEqual({
      navigate: null,
      open: planned,
    })
  })

  it('con el grupo completo no se toca nada', () => {
    const abiertas = planned.map((url, i) => pestana(i + 1, url))
    expect(reconcileGroup(planned, abiertas, PANEL)).toEqual({
      navigate: null,
      open: [],
    })
  })

  it('solo abre el enlace que falta', () => {
    const abiertas = [
      pestana(1, `${PANEL}/?space=sp1`),
      pestana(2, 'https://github.com/willy/muxspace'),
    ]
    expect(reconcileGroup(planned, abiertas, PANEL)).toEqual({
      navigate: null,
      open: ['https://docs.interno/muxspace'],
    })
  })

  it('lleva la pestaña del panel al espacio del proyecto en vez de abrir otra', () => {
    // El caso real: el grupo se creó cuando los proyectos no tenían espacio,
    // así que su pestaña del panel se quedó en «Sin asignar». Abrir dos
    // paneles en el mismo grupo no son dos cosas: es un duplicado.
    const abiertas = [
      pestana(7, `${PANEL}/`),
      pestana(8, 'https://github.com/willy/muxspace'),
      pestana(9, 'https://docs.interno/muxspace'),
    ]
    expect(reconcileGroup(planned, abiertas, PANEL)).toEqual({
      navigate: { tabId: 7, url: `${PANEL}/?space=sp1` },
      open: [],
    })
  })

  it('la pestaña del panel ya en su sitio no se navega', () => {
    // El control negativo del anterior: recargar la pestaña de alguien que ya
    // está donde toca le tiraría lo que estuviera haciendo.
    const abiertas = [pestana(7, `${PANEL}/?space=sp1`)]
    expect(reconcileGroup(planned, abiertas, PANEL).navigate).toBe(null)
  })

  it('una URL ilegible entre las abiertas no rompe el cálculo', () => {
    expect(reconcileGroup(planned, [pestana(1, 'about:blank')], PANEL)).toEqual({
      navigate: null,
      open: planned,
    })
  })

  it('un proyecto sin espacio deja la pestaña del panel donde está', () => {
    // Ya no le pasa a ningún proyecto (la migración les dio espacio), pero un
    // espacio borrado a mano devuelve `space: null` otra vez.
    const sinEspacio = plannedUrls({ space: null, links: [] }, `${PANEL}/`)
    const abiertas = [pestana(3, `${PANEL}/`)]
    expect(reconcileGroup(sinEspacio, abiertas, PANEL)).toEqual({
      navigate: null,
      open: [],
    })
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
