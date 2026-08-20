// Minimizar una terminal de a una.
//
// Lo que hay que demostrar no es que aparezca un botón, sino las dos
// propiedades que hacen que minimizar sirva de algo: la minimizada SIGUE
// montada (si se desmontara, se cerraría su WebSocket y perdería el
// scrollback) y las que quedan se reparten el espacio como si la otra no
// existiera. Por eso se monta el grid de verdad y se mira el `style` que
// acaba en cada tile.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import SessionGrid from './SessionGrid.jsx'

// La terminal real abre un WebSocket contra el backend: aquí solo interesa
// dónde la coloca el grid, así que se dobla por un marcador con su nombre.
vi.mock('./TerminalTile.jsx', () => ({
  default: ({ session, onMinimize }) => (
    <div data-testid={`tile-${session.name}`}>
      <button onClick={onMinimize}>minimizar {session.name}</button>
    </div>
  ),
}))

const sessions = [{ name: 'uno' }, { name: 'dos' }, { name: 'tres' }]

// Contenedor que el grid crea para cada tile (el padre del doble).
const wrapper = (name) => screen.getByTestId(`tile-${name}`).parentElement

function renderGrid(props = {}) {
  return render(
    <LangProvider>
      <SessionGrid
        openSessions={sessions}
        activeName={null}
        onSetActive={() => {}}
        onClose={() => {}}
        onKill={() => {}}
        onReorder={() => {}}
        commands={[]}
        layout="auto"
        focusedName={null}
        onSetFocused={() => {}}
        {...props}
      />
    </LangProvider>,
  )
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

describe('SessionGrid: minimizar', () => {
  it('el botón del tile pide minimizar esa sesión', () => {
    const minimizadas = []
    renderGrid({ onToggleMinimized: (name) => minimizadas.push(name) })

    fireEvent.click(screen.getByText('minimizar dos'))

    expect(minimizadas).toEqual(['dos'])
  })

  it('la minimizada sigue montada, pero fuera de la rejilla', () => {
    renderGrid({ minimizedNames: new Set(['dos']) })

    // Sigue en el DOM: no se ha desmontado, solo se ha escondido.
    expect(screen.getByTestId('tile-dos')).toBeInTheDocument()
    expect(wrapper('dos')).toHaveStyle({ display: 'none' })
  })

  it('las que quedan se reparten el espacio sin contar a la minimizada', () => {
    renderGrid({ minimizedNames: new Set(['dos']) })

    // Dos visibles => rejilla de 2 columnas: la primera pista y la tercera
    // (la segunda es el canal del separador).
    expect(wrapper('uno')).toHaveStyle({ gridColumn: '1', gridRow: '1' })
    expect(wrapper('tres')).toHaveStyle({ gridColumn: '3', gridRow: '1' })
  })

  it('la barra de arriba lista solo las minimizadas y las devuelve al grid', () => {
    const restauradas = []
    renderGrid({
      minimizedNames: new Set(['dos']),
      onToggleMinimized: (name) => restauradas.push(name),
    })

    const barra = screen.getByRole('button', { name: 'dos' }).parentElement
    expect(
      within(barra)
        .getAllByRole('button')
        .map((b) => b.textContent),
    ).toEqual(['dos'])

    fireEvent.click(screen.getByRole('button', { name: 'dos' }))
    expect(restauradas).toEqual(['dos'])
  })

  it('con todas minimizadas lo dice y deja volver desde la barra', () => {
    renderGrid({ minimizedNames: new Set(['uno', 'dos', 'tres']) })

    // El idioma por defecto en los tests es el inglés (no hay preferencia
    // guardada), así que el aviso se busca por su texto en inglés.
    expect(screen.getByText(/All terminals are minimized/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'uno' })).toBeInTheDocument()
    // Ninguna se ha desmontado por el camino.
    for (const { name } of sessions) {
      expect(screen.getByTestId(`tile-${name}`)).toBeInTheDocument()
    }
  })
})
