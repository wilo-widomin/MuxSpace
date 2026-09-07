// Enlaces generales del panel: los que no son de ningún proyecto.
//
// Viven en la cabecera del SIDEBAR, no en la de cada terminal: son del panel
// entero. Lo que hay que demostrar es que abren fuera sin darle control a la
// pestaña destino, y que el alta guarda lo que se escribe.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api.js'
import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import { LinkSettings } from './LinkSettings.jsx'
import { WebLinksMenu } from './WebLinksMenu.jsx'

const ENLACES = [
  { id: 'l1', title: 'Forgejo', url: 'https://git.example/muxspace' },
  { id: 'l2', title: 'Panel', url: 'https://panel.example' },
]

function abrirMenu(props = {}) {
  render(
    <LangProvider>
      <WebLinksMenu links={ENLACES} {...props} />
    </LangProvider>,
  )
  fireEvent.click(screen.getByLabelText(en['links.title']))
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('Menú de enlaces del panel', () => {
  it('cada uno abre su URL fuera del panel y sin control sobre esta pestaña', () => {
    abrirMenu()

    const forgejo = screen.getByRole('link', { name: 'Forgejo' })

    expect(forgejo).toHaveAttribute('href', 'https://git.example/muxspace')
    expect(forgejo).toHaveAttribute('target', '_blank')
    expect(forgejo.getAttribute('rel')).toContain('noopener')
  })

  it('el menú nace cerrado: el botón no llena la cabecera de enlaces', () => {
    render(
      <LangProvider>
        <WebLinksMenu links={ENLACES} />
      </LangProvider>,
    )

    expect(screen.queryByRole('link', { name: 'Forgejo' })).toBeNull()
  })

  it('sin enlaces guardados lo dice', () => {
    abrirMenu({ links: [] })

    expect(screen.getByText(en['links.empty'])).toBeInTheDocument()
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
