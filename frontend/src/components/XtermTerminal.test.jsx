// Cómo se redimensiona la terminal: cuándo se le pide el tamaño a tmux y
// cuándo se cambia el de xterm.
//
// Las dos reglas que se prueban aquí nacen del mismo fallo —la pantalla se
// quedaba con la misma línea repetida decenas de veces hasta recargar— y son
// las dos mitades de su arreglo:
//
//  1. Un tile con `display:none` (minimizado, o escondido por el modo foco) no
//     mide nada. FitAddon no mide píxeles: lee el `height`/`width` calculados
//     del contenedor, y con un ancestro oculto el navegador devuelve el
//     literal «100%», que el addon toma por 100 px (unas 11x5). Ese tamaño se
//     le mandaba a tmux, que redibujaba la sesión a 11 columnas.
//  2. xterm NO cambia de tamaño al medir, sino cuando el backend confirma que
//     el PTY ya lo ha hecho. Si cambiara antes, aplicaría con la geometría
//     nueva los bytes que tmux dibujó con la vieja, y ese desajuste no se
//     arregla solo: tmux dibuja por diferencias y da por bueno lo que cree que
//     el navegador ya tiene.
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'

const { proponer, resizeSpy } = vi.hoisted(() => ({
  proponer: vi.fn(),
  resizeSpy: vi.fn(),
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    proposeDimensions = proponer
  },
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 80
    rows = 24
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
    write(_datos, cb) {
      // xterm procesa lo escrito de forma asíncrona y avisa al terminar; el
      // componente usa ese aviso para redimensionar en el punto justo.
      if (cb) cb()
    }
    resize = resizeSpy
    focus() {}
    paste() {}
    dispose() {}
  },
}))

import XtermTerminal from './XtermTerminal.jsx'

let enviados = []
let observadores = []
let sockets = []
/** Tamaño que finge tener el contenedor. 0 = tile con `display:none`. */
let ancho = 800

class FakeWebSocket {
  static OPEN = 1
  readyState = 1
  binaryType = ''
  constructor() {
    sockets.push(this)
  }
  send(raw) {
    enviados.push(JSON.parse(raw))
  }
  close() {}
}

const descriptores = {}

beforeEach(() => {
  enviados = []
  observadores = []
  sockets = []
  ancho = 800
  resizeSpy.mockClear()
  proponer.mockReset()
  proponer.mockReturnValue({ cols: 120, rows: 40 })
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

function montar() {
  return render(
    <LangProvider>
      <XtermTerminal name="panel" />
    </LangProvider>,
  )
}

function dispararResize() {
  vi.useFakeTimers()
  for (const cb of observadores) cb()
  // El reajuste va agrupado con un temporizador de 60 ms.
  vi.advanceTimersByTime(100)
  vi.useRealTimers()
}

/** Simula el aviso del backend de que el PTY ya tiene ese tamaño. */
function llegaConfirmacion(cols, rows) {
  sockets[0].onmessage({ data: JSON.stringify({ type: 'resized', cols, rows }) })
}

const resizes = () => enviados.filter((m) => m.type === 'resize')

describe('XtermTerminal: tamaño', () => {
  it('con el contenedor sin tamaño no mide ni le pide nada a tmux', () => {
    montar()
    enviados = []
    proponer.mockClear()

    ancho = 0 // el tile pasa a display:none
    dispararResize()

    expect(proponer).not.toHaveBeenCalled()
    expect(resizes()).toEqual([])
  })

  it('al reaparecer pide el tamaño de verdad', () => {
    montar()
    ancho = 0
    dispararResize()
    enviados = []

    ancho = 800 // se restaura la ventana
    proponer.mockReturnValue({ cols: 90, rows: 30 })
    dispararResize()

    expect(resizes()).toEqual([{ type: 'resize', cols: 90, rows: 30 }])
  })

  it('no repite la petición si el tamaño no ha cambiado', () => {
    montar()
    dispararResize()
    expect(resizes()).toHaveLength(1)

    enviados = []
    dispararResize()

    expect(resizes()).toEqual([])
  })

  it('xterm no cambia de tamaño hasta que el backend confirma el del PTY', () => {
    montar()
    dispararResize()

    expect(resizeSpy).not.toHaveBeenCalled()

    llegaConfirmacion(120, 40)

    expect(resizeSpy).toHaveBeenCalledWith(120, 40)
  })
})

// Por qué esto merece un test: el fallo que arregla no se ve en jsdom ni en
// Playwright, porque es el navegador de verdad quien se queda el gesto. Para
// ver lo anterior en una tableta hay que arrastrar HACIA ABAJO, que es el
// «tirar para recargar» de Chrome en Android, y el navegador lo reclama en el
// primer `touchmove`. El gesto del panel cancela recién a los 10 px, así que
// llegaba tarde. Lo único que lo evita es que el contenedor declare que ahí
// dentro no hay gestos del navegador; lo que se comprueba es justo eso, que la
// declaración está en el DOM, porque es toda la causa y todo el arreglo.
describe('XtermTerminal: gestos táctiles', () => {
  it('la terminal no le deja ningún gesto al navegador', () => {
    const { container } = montar()
    const terminal = container.querySelector('.overflow-hidden')

    expect(terminal.style.touchAction).toBe('none')
  })

  it('el modal de la lupa NO queda dentro de esa zona', () => {
    // Si `touchAction: none` estuviera en el div padre, el modal lo heredaría
    // y se quedaría sin scroll ni selección nativos — que es precisamente
    // como se copia texto desde una tableta.
    const { container } = montar()
    const raiz = container.querySelector('.relative')

    expect(raiz.style.touchAction).toBe('')
  })
})
