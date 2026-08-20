// El selector de espacio del formulario de proyecto.
//
// El id del espacio es lo que la extensión del navegador mete en `?space=`
// al abrir el grupo de pestañas, así que lo que se prueba aquí es que ese
// id llega de verdad al guardar, y que el alta y la edición NO tratan igual
// el valor vacío: al crear significa "hazme uno", al editar "ninguno".
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import Sidebar from './Sidebar.jsx'

vi.mock('../api.js', async () => {
  const real = await vi.importActual('../api.js')
  return {
    ...real,
    api: new Proxy({}, { get: () => () => Promise.resolve([]) }),
  }
})

const LANG_KEY = 'muxspace:lang'

// El <select> de comandos solo ofrece los de la biblioteca: sin esto, el
// formulario de alta no se puede rellenar (ver `CommandSelect`).
const COMANDOS = [{ id: 'c1', label: 'Dev', command: 'bun dev' }]

const ESPACIOS = [
  { id: 'sp1', title: 'Clientes', order: 0 },
  { id: 'sp2', title: 'Interno', order: 1 },
]

const PROYECTO = {
  id: 'p1',
  title: 'Panel',
  cwd: '/srv',
  commands: ['bun dev'],
  links: [],
  space: 'sp2',
}

function props(extra = {}) {
  const noop = () => {}
  return {
    collapsed: false,
    onToggleCollapse: noop,
    width: 320,
    sessions: [],
    commands: COMANDOS,
    projects: [],
    openNames: [],
    spaces: ESPACIOS,
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
  localStorage.setItem(LANG_KEY, 'es')
  return render(
    <LangProvider>
      <Sidebar {...props(extra)} />
    </LangProvider>,
  )
}

/** Abre el modal de alta de proyecto. */
function abrirAlta() {
  fireEvent.click(screen.getByTitle('Nuevo proyecto'))
}

/** Abre el modal de edición del único proyecto de la lista. */
function abrirEdicion() {
  fireEvent.click(screen.getByTitle('Editar proyecto'))
}

/** El <select> de comandos del modal, que NO es el único de la página.

El sidebar tiene sus propios desplegables (el de espacio activo, el de
idioma), así que se localiza por lo único que lo distingue: es el que ofrece
el comando de la biblioteca. */
function selectorDeComandos() {
  const encontrado = screen
    .getAllByRole('combobox')
    .find((el) =>
      Array.from(el.querySelectorAll('option')).some((o) => o.value === 'bun dev'),
    )
  expect(encontrado).toBeTruthy()
  return encontrado
}

/** Rellena título y primer comando del alta, lo mínimo para poder guardar. */
function rellenarAlta() {
  fireEvent.change(screen.getByLabelText('Título'), {
    target: { value: 'Panel' },
  })
  fireEvent.change(selectorDeComandos(), { target: { value: 'bun dev' } })
}

describe('espacio del proyecto', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(cleanup)

  it('el alta manda el espacio elegido', async () => {
    const onSaveProject = vi.fn().mockResolvedValue({})
    montar({ onSaveProject })
    abrirAlta()

    fireEvent.change(screen.getByLabelText('Espacio'), {
      target: { value: 'sp1' },
    })
    rellenarAlta()
    fireEvent.click(screen.getByText('Guardar proyecto'))

    expect(onSaveProject).toHaveBeenCalledWith('Panel', null, ['bun dev'], [], 'sp1')
  })

  it('el alta sin elegir espacio manda null: el backend crea uno', () => {
    const onSaveProject = vi.fn().mockResolvedValue({})
    montar({ onSaveProject })
    abrirAlta()

    rellenarAlta()
    fireEvent.click(screen.getByText('Guardar proyecto'))

    expect(onSaveProject).toHaveBeenCalledWith('Panel', null, ['bun dev'], [], null)
  })

  it('el alta avisa de que se creará un espacio con el nombre del proyecto', () => {
    montar()
    abrirAlta()

    expect(
      screen.getByText(/se creará un espacio con el nombre del proyecto/i),
    ).toBeTruthy()
  })

  it('la edición precarga el espacio guardado y manda el que se elija', () => {
    const onUpdateProject = vi.fn().mockResolvedValue({})
    montar({ projects: [PROYECTO], onUpdateProject })
    abrirEdicion()

    const selector = screen.getByLabelText('Espacio')
    expect(selector.value).toBe('sp2')

    fireEvent.change(selector, { target: { value: 'sp1' } })
    fireEvent.click(screen.getByText('Guardar'))

    expect(onUpdateProject).toHaveBeenCalledWith(
      'p1',
      'Panel',
      '/srv',
      ['bun dev'],
      [],
      'sp1',
    )
  })
})
