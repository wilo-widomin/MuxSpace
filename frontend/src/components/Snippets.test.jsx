// Textos rápidos: se ESCRIBEN en la terminal y no se ejecutan.
//
// Esa distinción es toda la feature, así que es lo que se prueba: el texto
// elegido llega a la terminal por la vía de pegar (la misma del redactor) y
// NO por la de enviar un comando, que es la que lleva Enter implícito.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api.js'
import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import { SnippetSettings } from './SnippetSettings.jsx'
import TerminalTile from './TerminalTile.jsx'

// La terminal real abre un WebSocket; aquí solo interesa QUÉ se le pide
// pegar, así que el doble lo saca al DOM.
vi.mock('./XtermTerminal.jsx', () => ({
  default: ({ pasteRequest }) => (
    <div data-testid="terminal" data-pegado={pasteRequest?.text || ''} />
  ),
}))

const TEXTOS = [
  { id: 's1', label: 'Revisar', text: '/code-review high' },
  { id: 's2', label: 'Desplegar', text: '/desplegar' },
]

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
        snippets={TEXTOS}
        {...props}
      />
    </LangProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('Textos rápidos en la terminal', () => {
  it('elegir uno lo escribe en la terminal sin enviarlo', () => {
    const enviar = vi.spyOn(api, 'sendCommand').mockResolvedValue({})
    renderTile()

    fireEvent.click(screen.getByLabelText(en['tile.type_snippet']))
    fireEvent.click(screen.getByText('Revisar'))

    expect(screen.getByTestId('terminal')).toHaveAttribute(
      'data-pegado',
      '/code-review high',
    )
    // Lo que NO puede pasar: que se ejecute. `sendCommand` es el camino de
    // los Comandos, y ese sí manda Enter.
    expect(enviar).not.toHaveBeenCalled()
  })

  it('sin textos guardados lo dice, en vez de un desplegable vacío', () => {
    renderTile({ snippets: [] })

    fireEvent.click(screen.getByLabelText(en['tile.type_snippet']))

    expect(screen.getByText(en['tile.no_snippets'])).toBeInTheDocument()
  })
})

describe('Ajustes de los textos rápidos', () => {
  it('guarda uno nuevo y lo muestra en la lista', async () => {
    vi.spyOn(api, 'listSnippets')
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([TEXTOS[0]])
    const crear = vi.spyOn(api, 'createSnippet').mockResolvedValue(TEXTOS[0])
    render(
      <LangProvider>
        <SnippetSettings onClose={() => {}} />
      </LangProvider>,
    )
    await screen.findByText(en['snippets.empty'])

    fireEvent.change(screen.getByPlaceholderText(en['snippets.label_placeholder']), {
      target: { value: 'Revisar' },
    })
    fireEvent.change(screen.getByPlaceholderText(en['snippets.text_placeholder']), {
      target: { value: '/code-review high' },
    })
    fireEvent.click(screen.getByRole('button', { name: en['snippets.add'] }))

    await waitFor(() => expect(crear).toHaveBeenCalledWith('Revisar', '/code-review high'))
    expect(await screen.findByText('Revisar')).toBeInTheDocument()
  })

  it('un texto vacío no se intenta guardar', async () => {
    vi.spyOn(api, 'listSnippets').mockResolvedValue([])
    const crear = vi.spyOn(api, 'createSnippet').mockResolvedValue({})
    render(
      <LangProvider>
        <SnippetSettings onClose={() => {}} />
      </LangProvider>,
    )
    await screen.findByText(en['snippets.empty'])

    fireEvent.click(screen.getByRole('button', { name: en['snippets.add'] }))

    expect(crear).not.toHaveBeenCalled()
  })
})
