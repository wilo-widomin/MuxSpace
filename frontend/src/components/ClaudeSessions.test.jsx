import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { LangProvider } from '../i18n/index.jsx'
import { ClaudeSnippet } from './ClaudeSnippet.jsx'
import { ClaudeSessions } from './ClaudeSessions.jsx'
import { api, ApiError } from '../api.js'

const conIdioma = (ui) => render(<LangProvider>{ui}</LangProvider>)

describe('ClaudeSnippet', () => {
  it('el HTML del fragmento sale como texto, nunca como elementos', () => {
    const { container } = conIdioma(
      <ClaudeSnippet
        segments={[
          { text: '<img src=x onerror=alert(1)> y ', mark: false, secret: false },
          { text: '<b>negrita</b>', mark: true, secret: false },
        ]}
      />,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(container.textContent).toContain('<b>negrita</b>')
  })

  it('resalta solo lo marcado, con <mark>', () => {
    const { container } = conIdioma(
      <ClaudeSnippet
        segments={[
          { text: 'antes ', mark: false, secret: false },
          { text: 'clave', mark: true, secret: false },
          { text: ' después', mark: false, secret: false },
        ]}
      />,
    )
    const marcas = container.querySelectorAll('mark')
    expect(marcas).toHaveLength(1)
    expect(marcas[0].textContent).toBe('clave')
  })

  it('un secreto sale tapado y se enseña con «mostrar» por trozo', () => {
    const { container } = conIdioma(
      <ClaudeSnippet
        segments={[
          { text: 'a ', mark: false, secret: false },
          { text: 'sk-abcdefghijklmnop', mark: false, secret: true },
          { text: ' b ', mark: false, secret: false },
          { text: 'ghp_zzzzzzzzzzzzzzzzzzzz', mark: false, secret: true },
        ]}
      />,
    )
    expect(container.textContent).not.toContain('sk-abcdefghijklmnop')
    expect(container.textContent).not.toContain('ghp_zzzz')
    const botones = screen.getAllByRole('button')
    expect(botones).toHaveLength(2)
    fireEvent.click(botones[0])
    expect(container.textContent).toContain('sk-abcdefghijklmnop')
    // El otro sigue tapado.
    expect(container.textContent).not.toContain('ghp_zzzz')
    fireEvent.click(screen.getAllByRole('button')[0])
    expect(container.textContent).not.toContain('sk-abcdefghijklmnop')
  })
})

describe('ClaudeSessions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.setItem('muxspace:lang', 'es')
  })

  it('muestra el 503 con el mensaje y el comando literales', async () => {
    vi.spyOn(api, 'claudeSessions').mockRejectedValue(
      new ApiError(503, {
        code: 'err.claude_sessions_disabled',
        mensaje: 'Apagadas en el servidor.',
        detail: 'Para activarlas: touch /ruta/flag',
      }),
    )
    conIdioma(
      <ClaudeSessions
        project={{ id: 'p', title: 'P' }}
        onClose={() => {}}
        onResume={vi.fn()}
      />,
    )
    expect(await screen.findByText('Apagadas en el servidor.')).toBeInTheDocument()
    expect(screen.getByText('Para activarlas: touch /ruta/flag')).toBeInTheDocument()
  })

  it('lista, busca y retoma desde un proyecto', async () => {
    vi.spyOn(api, 'claudeSessions').mockResolvedValue({
      sessions: [
        {
          id: '11111111-2222-3333-4444-555555555555',
          title: 'Una charla',
          project: '/p/x',
          last_ts: new Date(2026, 10, 27, 10).toISOString(),
          n_messages: 4,
        },
      ],
    })
    const buscar = vi.spyOn(api, 'claudeSessionsSearch').mockResolvedValue({ hits: [] })
    const onResume = vi.fn().mockResolvedValue()
    conIdioma(
      <ClaudeSessions
        project={{ id: 'p', title: 'P' }}
        onClose={() => {}}
        onResume={onResume}
      />,
    )
    expect(await screen.findByText('Una charla')).toBeInTheDocument()
    expect(screen.getByText('27/11/2026')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Retomar' }))
    await waitFor(() =>
      expect(onResume).toHaveBeenCalledWith(
        '11111111-2222-3333-4444-555555555555',
        'p',
      ),
    )

    fireEvent.change(screen.getByPlaceholderText('Buscar en las conversaciones…'), {
      target: { value: 'hola' },
    })
    fireEvent.submit(
      screen.getByPlaceholderText('Buscar en las conversaciones…').closest('form'),
    )
    await waitFor(() => expect(buscar).toHaveBeenCalled())
    expect(buscar.mock.calls[0][0]).toMatchObject({ q: 'hola', project_id: 'p' })
  })
})
