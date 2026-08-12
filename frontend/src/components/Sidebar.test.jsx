// El acordeón del sidebar y `suggestName`.
//
// El acordeón se prueba montando el componente de verdad y no llamando a
// `setOpenSection` a mano: la propiedad que importa —"solo una abierta a la
// vez"— vive en el `toggleSection` Y en cómo se pasa `open` a cada persiana,
// y una de las dos por separado no la demuestra.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import Sidebar, { suggestName } from './Sidebar.jsx'

// Las persianas de pegar/subir piden datos al montar. No es lo que se está
// probando, así que se dobla la API entera con respuestas vacías: sin esto
// los tests dependerían de la red y llenarían la consola de errores.
vi.mock('../api.js', async () => {
  const real = await vi.importActual('../api.js')
  return {
    ...real,
    api: new Proxy({}, { get: () => () => Promise.resolve([]) }),
  }
})

const SECTION_KEY = 'muxspace-sidebar-section'
const LANG_KEY = 'muxspace:lang'

/** Props mínimas para que `Sidebar` renderice. Todo lo demás son no-ops. */
function props(extra = {}) {
  const noop = () => {}
  return {
    collapsed: false,
    onToggleCollapse: noop,
    width: 320,
    sessions: [],
    commands: [],
    projects: [],
    openNames: [],
    spaces: [],
    activeSpace: null,
    onSetActiveSpace: noop,
    onCreateSpace: noop,
    onRenameSpace: noop,
    onDeleteSpace: noop,
    onAssignSpace: noop,
    loading: false,
    error: null,
    onSelect: noop,
    onHideTile: noop,
    onCreate: noop,
    onRenameSession: noop,
    onKillSession: noop,
    onRunCommand: noop,
    onRunProject: noop,
    onRunProjectInNewTab: noop,
    onSaveCommand: noop,
    onUpdateCommand: noop,
    onDeleteCommand: noop,
    onSaveProject: noop,
    onUpdateProject: noop,
    onDeleteProject: noop,
    onRefresh: noop,
    layout: 'auto',
    onSetLayout: noop,
    onLogout: noop,
    ...extra,
  }
}

function montar(extra) {
  // Idioma FIJO. Sin esto, `resolveLang` cae a `navigator.language`, que en
  // jsdom es en-US y en la máquina de quien desarrolla puede ser otro: los
  // selectores por texto pasarían o fallarían según dónde corra el test.
  localStorage.setItem(LANG_KEY, 'es')
  return render(
    <LangProvider>
      <Sidebar {...props(extra)} />
    </LangProvider>,
  )
}

/** El triángulo de una persiana dice si está abierta: ▾ abierta, ▸ cerrada. */
function abiertas() {
  return screen.queryAllByText('▾').length
}

// Las cuatro cabeceras de persiana son los botones cuyo contenido es el
// triángulo (el título va en un elemento hermano, fuera del botón). Se
// localizan así y no por texto traducido ni por posición: el idioma y el
// orden del DOM son detalles que pueden cambiar sin que el acordeón deje de
// ser un acordeón.
function cabeceras() {
  const botones = screen
    .getAllByRole('button')
    .filter((b) => /[▾▸]/.test(b.textContent || ''))
  expect(botones).toHaveLength(4)
  return botones
}

/** Índice de la persiana abierta, o -1 si están todas cerradas. */
function indiceAbierta() {
  return cabeceras().findIndex((b) => (b.textContent || '').includes('▾'))
}

describe('acordeón del sidebar', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('arranca con una sola sección abierta', () => {
    montar()
    expect(abiertas()).toBe(1)
  })

  it('abrir una cierra las demás', () => {
    montar()
    // Se recorren las cuatro: tras cada clic, como mucho una abierta. Y al
    // abrir una concreta, es ESA la que queda abierta.
    for (let i = 0; i < 4; i += 1) {
      const abiertaAntes = indiceAbierta()
      fireEvent.click(cabeceras()[i])
      expect(abiertas()).toBeLessThanOrEqual(1)
      // Pulsar la que ya estaba abierta la cierra; pulsar otra la abre.
      expect(indiceAbierta()).toBe(abiertaAntes === i ? -1 : i)
    }
  })

  it('volver a pulsar la abierta la cierra', () => {
    montar()
    const abierta = indiceAbierta()
    expect(abierta).toBeGreaterThanOrEqual(0)

    fireEvent.click(cabeceras()[abierta])

    expect(abiertas()).toBe(0)
    // Cerrada del todo se guarda como cadena vacía, no se borra la clave:
    // así al volver se restaura "todas cerradas" y no el valor por defecto.
    expect(localStorage.getItem(SECTION_KEY)).toBe('')
  })

  it('persiste en localStorage la sección que se abre', () => {
    montar()
    const otra = (indiceAbierta() + 1) % 4

    fireEvent.click(cabeceras()[otra])

    const guardada = localStorage.getItem(SECTION_KEY)
    expect(guardada).toBeTruthy()
    // Y lo guardado es lo que se restaura: al montar de nuevo con ese valor,
    // la abierta vuelve a ser la misma.
    cleanup()
    montar()
    expect(indiceAbierta()).toBe(otra)
  })

  it('restaura la sección guardada al volver a montar', () => {
    localStorage.setItem(SECTION_KEY, 'commands')

    montar()

    // Sin la restauración arrancaría en 'projects' y este texto no estaría
    // desplegado.
    expect(abiertas()).toBe(1)
    expect(localStorage.getItem(SECTION_KEY)).toBe('commands')
  })

  it('un valor basura en localStorage no rompe el render', () => {
    // No es teoría: el usuario puede tener ahí el valor de una versión vieja
    // del panel. El componente tiene que pintar igual.
    localStorage.setItem(SECTION_KEY, 'seccion-que-no-existe')

    expect(() => montar()).not.toThrow()
    // Ninguna sección casa con ese nombre, así que no hay ninguna abierta.
    expect(abiertas()).toBe(0)
  })
})

describe('suggestName', () => {
  it('sin sesiones propone sesion-1', () => {
    expect(suggestName([])).toBe('sesion-1')
  })

  it('salta los nombres ocupados', () => {
    expect(suggestName(['sesion-1', 'sesion-2'])).toBe('sesion-3')
  })

  it('NUNCA devuelve un nombre ocupado, aunque haya huecos', () => {
    // La propiedad de verdad no es "rellena huecos" —eso es una decisión de
    // diseño— sino "el nombre que propone está libre". Se comprueba sobre
    // varias formas de ocupación, incluida la que tiene hueco.
    for (const ocupados of [
      ['sesion-1', 'sesion-3'],
      ['sesion-2', 'sesion-3'],
      ['sesion-1', 'sesion-2', 'sesion-3', 'sesion-4'],
      ['otra-cosa', 'sesion-1'],
    ]) {
      expect(ocupados).not.toContain(suggestName(ocupados))
    }
  })

  it('ignora los nombres que no siguen el patrón', () => {
    expect(suggestName(['trabajo', 'notas'])).toBe('sesion-1')
  })
})

describe('fila de sesión', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  const sesion = { name: 'trabajo', windows: 3, attached: true, space: null }

  /** Monta el sidebar con una sesión suelta visible en «Sin asignar». */
  function conSesion(extra = {}) {
    return montar({ sessions: [sesion], activeSpace: 'unassigned', ...extra })
  }

  it('no escribe el estado ni el número de ventanas junto al nombre', () => {
    // El ancho de la fila es el presupuesto del NOMBRE, que es lo único que
    // distingue una sesión de otra. Ni «abierta» —que ya se ve por el fondo
    // de la fila y por la ✕ de ocultar— ni el contador de ventanas de tmux
    // valían lo que costaban.
    conSesion({ openNames: ['trabajo'] })

    expect(screen.getByText('trabajo')).toBeTruthy()
    expect(screen.queryByText('abierta')).toBeNull()
    expect(screen.queryByText(/ventana/)).toBeNull()
  })

  it('el selector de espacio sigue siendo alcanzable por su nombre', () => {
    // Se dibuja como un icono, con el <select> nativo encima e invisible.
    // Que sea invisible es cosa del CSS: el control tiene que seguir
    // existiendo, con nombre accesible, y asignar al cambiarlo.
    const onAssignSpace = vi.fn(() => Promise.resolve())
    conSesion({
      spaces: [{ id: 'esp-1', title: 'Trabajo' }],
      onAssignSpace,
    })

    const selector = screen.getByRole('combobox', { name: 'Mover a otro espacio' })
    fireEvent.change(selector, { target: { value: 'esp-1' } })

    expect(onAssignSpace).toHaveBeenCalledWith('trabajo', 'esp-1')
  })
})
