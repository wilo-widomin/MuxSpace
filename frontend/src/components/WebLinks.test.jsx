// Enlaces generales del panel: los que no son de ningún proyecto.
//
// Lo que hay que demostrar es que abren fuera del panel sin darle control a
// la pestaña destino, y que no se mezclan con las badges del proyecto, que
// viven en la misma cabecera y se parecen mucho.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api.js'
import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import { LinkSettings } from './LinkSettings.jsx'
import TerminalTile from './TerminalTile.jsx'

vi.mock('./XtermTerminal.jsx', () => ({ default: () => <div /> }))

const ENLACES = [
  { id: 'l1', title: 'Forgejo', url: 'https://git.example/muxspace' },
  { id: 'l2', title: 'Panel', url: 'https://panel.example' },
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
        webLinks={ENLACES}
        {...props}
      />
    </LangProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('Enlaces generales en la terminal', () => {
  it('cada uno abre su URL fuera del panel y sin control sobre esta pestaña', () => {
    renderTile()

    fireEvent.click(screen.getByLabelText(en['tile.links']))
    const forgejo = screen.getByRole('link', { name: 'Forgejo' })

    expect(forgejo).toHaveAttribute('href', 'https://git.example/muxspace')
    expect(forgejo).toHaveAttribute('target', '_blank')
    expect(forgejo.getAttribute('rel')).toContain('noopener')
  })

  it('no se mezclan con las badges del proyecto', () => {
    renderTile({ links: [{ url: 'https://repo.example', title: 'Del proyecto' }] })

    // Cerrado el menú, en la cabecera solo está la badge del proyecto.
    expect(screen.getByRole('link', { name: 'Del proyecto' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Forgejo' })).toBeNull()
  })

  it('sin enlaces guardados lo dice', () => {
    renderTile({ webLinks: [] })

    fireEvent.click(screen.getByLabelText(en['tile.links']))

    expect(screen.getByText(en['tile.no_links'])).toBeInTheDocument()
  })
})

describe('Ajustes de los enlaces', () => {
  it('guarda uno nuevo y lo muestra en la lista', async () => {
    vi.spyOn(api, 'listLinks')
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([ENLACES[0]])
    const crear = vi.spyOn(api, 'createLink').mockResolvedValue(ENLACES[0])
    render(
      <LangProvider>
        <LinkSettings onClose={() => {}} />
      </LangProvider>,
    )
    await screen.findByText(en['links.empty'])

    fireEvent.change(screen.getByPlaceholderText(en['links.title_placeholder']), {
      target: { value: 'Forgejo' },
    })
    fireEvent.change(screen.getByPlaceholderText(en['links.url_placeholder']), {
      target: { value: 'https://git.example/muxspace' },
    })
    fireEvent.click(screen.getByRole('button', { name: en['links.add'] }))

    await waitFor(() =>
      expect(crear).toHaveBeenCalledWith('Forgejo', 'https://git.example/muxspace'),
    )
    expect(await screen.findByText('Forgejo')).toBeInTheDocument()
  })

  it('sin dirección no se intenta guardar', async () => {
    vi.spyOn(api, 'listLinks').mockResolvedValue([])
    const crear = vi.spyOn(api, 'createLink').mockResolvedValue({})
    render(
      <LangProvider>
        <LinkSettings onClose={() => {}} />
      </LangProvider>,
    )
    await screen.findByText(en['links.empty'])

    fireEvent.click(screen.getByRole('button', { name: en['links.add'] }))

    expect(crear).not.toHaveBeenCalled()
  })
})
