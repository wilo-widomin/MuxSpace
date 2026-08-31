// La marca de "esta sesión te reclama", en el tile y en el sidebar.
//
// Lo que hay que demostrar es lo que el usuario ve y hace: que la marca
// aparece, que se distingue del punto de estado normal, y que atender la
// terminal —enfocarla o teclear en ella— es lo que la apaga. El transporte
// (el bus de eventos) se prueba en el backend.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
// El idioma lo resuelve el navegador, y en jsdom eso es el inglés: los textos
// se leen del diccionario en vez de escribirlos a mano, que si no el test
// pasaría a depender de la locale de la máquina que lo ejecuta.
import en from '../i18n/locales/en.json'
import TerminalTile from './TerminalTile.jsx'

// La terminal real abre un WebSocket; aquí se sustituye por un botón que
// dispara `onActivity`, que es lo que hace teclear en ella.
vi.mock('./XtermTerminal.jsx', () => ({
  default: ({ onActivity }) => (
    <button type="button" onClick={() => onActivity?.()}>
      teclear
    </button>
  ),
}))

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

describe('Marca de atención en la terminal', () => {
  it('una sesión que reclama enseña la etiqueta que mandó quien la marcó', () => {
    renderTile({
      session: { name: 'panel', attention: { at: 1, label: 'espera tu respuesta' } },
    })

    expect(screen.getByTitle('espera tu respuesta')).toBeInTheDocument()
  })

  it('sin etiqueta se explica igual, con el texto del panel', () => {
    renderTile({ session: { name: 'panel', attention: { at: 1, label: null } } })

    expect(screen.getByTitle(en['tile.attention'])).toBeInTheDocument()
  })

  it('una sesión tranquila no lleva ninguna marca', () => {
    renderTile()

    expect(screen.queryByTitle(en['tile.attention'])).not.toBeInTheDocument()
  })

  it('teclear en la terminal la da por atendida', () => {
    const onAttended = vi.fn()
    renderTile({
      session: { name: 'panel', attention: { at: 1 } },
      onAttended,
    })

    fireEvent.click(screen.getByRole('button', { name: 'teclear' }))

    expect(onAttended).toHaveBeenCalledWith('panel')
  })
})
