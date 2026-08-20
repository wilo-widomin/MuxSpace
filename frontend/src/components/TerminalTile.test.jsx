// Enlaces del proyecto en la cabecera de la terminal.
//
// Lo que hay que demostrar no es que se pinte un texto, sino que la badge es
// un ENLACE utilizable: con su URL, que se abre fuera del panel y sin darle
// a la pestaña destino control sobre esta (`rel="noopener"`). Y que una
// sesión sin proyecto no gana ningún adorno.
import { cleanup, render, screen } from '@testing-library/react'
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
