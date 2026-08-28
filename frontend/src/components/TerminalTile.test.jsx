// Enlaces del proyecto en la cabecera de la terminal.
//
// Lo que hay que demostrar no es que se pinte un texto, sino que la badge es
// un ENLACE utilizable: con su URL, que se abre fuera del panel y sin darle
// a la pestaña destino control sobre esta (`rel="noopener"`). Y que una
// sesión sin proyecto no gana ningún adorno.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import TerminalTile from './TerminalTile.jsx'

// La terminal real abre un WebSocket contra el backend; aquí solo interesa
// la cabecera.
vi.mock('./XtermTerminal.jsx', () => ({ default: () => <div /> }))

function renderTile(props = {}) {
  return render(
    <LangProvider>
      <TerminalTile
        session={{ name: 'panel' }}
        isActive={false}
        onFocus={() => {}}
        onClose={() => {}}
        onKill={() => {}}
        onMinimize={() => {}}
        onToggleFocus={() => {}}
        {...props}
      />
    </LangProvider>,
  )
}

afterEach(cleanup)

describe('TerminalTile: enlaces del proyecto', () => {
  it('cada enlace es una badge que abre su URL fuera del panel', () => {
    renderTile({
      links: [
        { url: 'https://forgejo.example/muxspace', title: 'Repo' },
        { url: 'https://panel.example', title: 'Panel' },
      ],
    })

    const repo = screen.getByRole('link', { name: 'Repo' })

    expect(repo).toHaveAttribute('href', 'https://forgejo.example/muxspace')
    expect(repo).toHaveAttribute('target', '_blank')
    // Sin `noopener`, la página abierta puede redirigir a la del panel.
    expect(repo.getAttribute('rel')).toContain('noopener')
    expect(screen.getAllByRole('link')).toHaveLength(2)
  })

  it('una sesión sin proyecto no pinta ninguna badge', () => {
    renderTile()

    expect(screen.queryAllByRole('link')).toHaveLength(0)
    expect(screen.getByText('panel')).toBeInTheDocument()
  })
})

describe('TerminalTile: otra terminal en el mismo directorio', () => {
  it('el icono de terminal pide una nueva para ESTA sesión', () => {
    const onSpawn = vi.fn()
    renderTile({ session: { name: 'muxspace' }, onSpawn })

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Open another terminal in this same directory',
      }),
    )

    // El nombre es lo único que viaja: el directorio lo resuelve el backend
    // leyendo el panel de tmux de esa sesión.
    expect(onSpawn).toHaveBeenCalledWith('muxspace')
  })
})

describe('TerminalTile: el desplegable de comandos', () => {
  it('Escape lo cierra aunque el foco esté fuera del filtro', () => {
    renderTile({ commands: [{ id: '1', label: 'build', command: 'bun run build' }] })
    fireEvent.click(
      screen.getByRole('button', { name: 'Run a command from the library' }),
    )
    expect(screen.getByPlaceholderText('Filter commands…')).toBeInTheDocument()

    // El foco se va del filtro en cuanto se pincha la lista o la terminal:
    // por eso el Escape se prueba sobre `window`, no sobre el input.
    fireEvent.keyDown(window, { key: 'Escape' })

    expect(screen.queryByPlaceholderText('Filter commands…')).not.toBeInTheDocument()
  })
})

describe('TerminalTile: renombrar desde la cabecera', () => {
  it('el doble clic sobre el nombre lo convierte en un campo editable', async () => {
    const onRename = vi.fn().mockResolvedValue(undefined)
    renderTile({ session: { name: 'muxspace-2' }, onRename })

    fireEvent.doubleClick(screen.getByText('muxspace-2'))
    const campo = screen.getByRole('textbox', { name: 'Rename the session' })
    // Arrancar con el nombre puesto es lo que permite retocarlo en vez de
    // teclearlo entero.
    expect(campo).toHaveValue('muxspace-2')

    fireEvent.change(campo, { target: { value: '  despliegue  ' } })
    fireEvent.submit(campo)

    // El nombre viaja recortado: un espacio al final no es un nombre distinto.
    expect(onRename).toHaveBeenCalledWith('muxspace-2', 'despliegue')
  })

  it('Escape cancela y deja el nombre como estaba', () => {
    const onRename = vi.fn()
    renderTile({ session: { name: 'muxspace-2' }, onRename })

    fireEvent.doubleClick(screen.getByText('muxspace-2'))
    const campo = screen.getByRole('textbox', { name: 'Rename the session' })
    fireEvent.change(campo, { target: { value: 'otro' } })
    fireEvent.keyDown(campo, { key: 'Escape' })

    expect(onRename).not.toHaveBeenCalled()
    expect(screen.getByText('muxspace-2')).toBeInTheDocument()
  })

  it('un nombre vacío no llega al servidor', () => {
    const onRename = vi.fn()
    renderTile({ session: { name: 'muxspace-2' }, onRename })

    fireEvent.doubleClick(screen.getByText('muxspace-2'))
    const campo = screen.getByRole('textbox', { name: 'Rename the session' })
    fireEvent.change(campo, { target: { value: '   ' } })
    fireEvent.submit(campo)

    expect(onRename).not.toHaveBeenCalled()
  })
})
