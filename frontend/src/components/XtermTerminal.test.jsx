// Redimensionado de la terminal cuando el tile NO se ve.
//
// Minimizar una ventana (o maximizar otra) no desmonta su terminal: le pone
// `display:none`. FitAddon no mide píxeles, lee el `height`/`width` calculados
// del contenedor —aquí `h-full w-full`—, y con un ancestro oculto el navegador
// devuelve el literal «100%», que el addon toma por 100 px: ~11x5. Esas
// dimensiones se le mandaban a tmux, que redibujaba la sesión a 11 columnas y
// dejaba el historial hecho un amasijo. Lo que se prueba es que con el
// contenedor sin tamaño no se mide ni se avisa a tmux, y que al reaparecer sí.
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'

const { fitSpy } = vi.hoisted(() => ({ fitSpy: vi.fn() }))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = fitSpy
  },
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 120
    rows = 40
    element = document.createElement('div')
    parser = { registerOscHandler: () => {} }
    loadAddon() {}
    open() {}
    onData() {
      return { dispose() {} }
    }
    attachCustomKeyEventHandler() {}
    hasSelection() {
      return false
    }
    getSelection() {
      return ''
    }
    write() {}
    focus() {}
    paste() {}
    dispose() {}
  },
}))

import XtermTerminal from './XtermTerminal.jsx'

// Mensajes de control que la terminal manda por el WebSocket.
let enviados = []
// Callbacks vivos del ResizeObserver: los dispara el test a mano, porque
// jsdom no observa nada de verdad.
let observadores = []
// Tamaño que finge tener el contenedor. 0 = tile con `display:none`.
let ancho = 0

class FakeWebSocket {
  static OPEN = 1
  readyState = 1
  binaryType = ''
  send(raw) {
    enviados.push(JSON.parse(raw))
  }
  close() {}
}

const descriptores = {}

beforeEach(() => {
  enviados = []
  observadores = []
  ancho = 800
  fitSpy.mockClear()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(cb) {
        observadores.push(cb)
      }
      observe() {}
      disconnect() {}
    },
  )
  // jsdom no hace layout: todo mide 0. Sin esto no se distingue «oculto» de
  // «visible» y el test no probaría nada.
  for (const prop of ['offsetWidth', 'offsetHeight']) {
    descriptores[prop] = Object.getOwnPropertyDescriptor(HTMLElement.prototype, prop)
    Object.defineProperty(HTMLElement.prototype, prop, {
      configurable: true,
      get: () => ancho,
    })
  }
})

afterEach(() => {
  for (const [prop, desc] of Object.entries(descriptores)) {
    if (desc) Object.defineProperty(HTMLElement.prototype, prop, desc)
  }
  vi.unstubAllGlobals()
})

function dispararResize() {
  vi.useFakeTimers()
  for (const cb of observadores) cb()
  // El reajuste va agrupado con un temporizador de 60 ms.
  vi.advanceTimersByTime(100)
  vi.useRealTimers()
}

const resizes = () => enviados.filter((m) => m.type === 'resize')

describe('XtermTerminal: tile oculto', () => {
  it('con el contenedor sin tamaño no mide ni le manda el tamaño a tmux', () => {
    render(
      <LangProvider>
        <XtermTerminal name="panel" />
      </LangProvider>,
    )
    enviados = []
    fitSpy.mockClear()

    ancho = 0 // el tile pasa a display:none
    dispararResize()

    expect(fitSpy).not.toHaveBeenCalled()
    expect(resizes()).toEqual([])
  })

  it('al reaparecer vuelve a medir y avisa con el tamaño de verdad', () => {
    render(
      <LangProvider>
        <XtermTerminal name="panel" />
      </LangProvider>,
    )
    ancho = 0
    dispararResize()
    enviados = []
    fitSpy.mockClear()

    ancho = 800 // se restaura la ventana
    dispararResize()

    expect(fitSpy).toHaveBeenCalled()
    expect(resizes()).toEqual([{ type: 'resize', cols: 120, rows: 40 }])
  })
})
