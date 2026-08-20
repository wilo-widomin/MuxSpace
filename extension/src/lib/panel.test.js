// La dirección del panel la escribe el usuario a mano, así que lo que se
// prueba aquí es que se le perdone teclear de menos sin que por eso la
// extensión acabe pidiendo permisos sobre cosas raras.
import { describe, expect, it } from 'vitest'

import {
  isPanelUrl,
  normalizePanelOrigin,
  originPattern,
  panelSpaceUrl,
} from './panel.js'

describe('normalizePanelOrigin', () => {
  it('sin esquema asume https: es como está publicado el panel', () => {
    expect(normalizePanelOrigin('panel.interno')).toBe('https://panel.interno')
  })

  it('respeta el puerto y el http explícito', () => {
    expect(normalizePanelOrigin('http://10.0.0.2:8000')).toBe('http://10.0.0.2:8000')
  })

  it('se queda con el origen y tira la ruta', () => {
    expect(normalizePanelOrigin('https://panel.interno/dashboard?x=1')).toBe(
      'https://panel.interno',
    )
  })

  it('perdona los espacios de alrededor', () => {
    expect(normalizePanelOrigin('  panel.interno  ')).toBe('https://panel.interno')
  })

  it('rechaza lo que no es http(s)', () => {
    // El control negativo que importa: de aquí sale el patrón de permisos que
    // se le pide a Chrome.
    expect(normalizePanelOrigin('file:///etc/passwd')).toBe('')
    expect(normalizePanelOrigin('javascript:alert(1)')).toBe('')
  })

  it('vacío se queda vacío', () => {
    expect(normalizePanelOrigin('')).toBe('')
    expect(normalizePanelOrigin(null)).toBe('')
  })
})

describe('panelSpaceUrl', () => {
  it('apunta al espacio del proyecto', () => {
    expect(panelSpaceUrl('https://panel.interno', 'sp1')).toBe(
      'https://panel.interno/?space=sp1',
    )
  })

  it('sin espacio abre el panel a secas', () => {
    // Le pasa a un proyecto cuyo espacio se borró: el backend devuelve null.
    expect(panelSpaceUrl('https://panel.interno', null)).toBe('https://panel.interno/')
  })

  it('escapa el id en vez de meterlo tal cual en la URL', () => {
    expect(panelSpaceUrl('https://panel.interno', 'a b&c')).toBe(
      'https://panel.interno/?space=a%20b%26c',
    )
  })
})

describe('originPattern', () => {
  it('cubre el panel entero y nada más', () => {
    expect(originPattern('https://panel.interno')).toBe('https://panel.interno/*')
  })
})

describe('isPanelUrl', () => {
  it('reconoce una pestaña del panel', () => {
    expect(isPanelUrl('https://panel.interno/?space=sp1', 'https://panel.interno')).toBe(
      true,
    )
  })

  it('no confunde otro host que empieza igual', () => {
    expect(isPanelUrl('https://panel.interno.evil.com/', 'https://panel.interno')).toBe(
      false,
    )
  })

  it('una URL ilegible no es el panel', () => {
    expect(isPanelUrl('no-es-una-url', 'https://panel.interno')).toBe(false)
    expect(isPanelUrl('', 'https://panel.interno')).toBe(false)
  })
})
