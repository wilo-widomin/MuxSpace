// Apagar el host: el botón existe solo si el servidor lo ofrece, y no se envía
// nada sin escribir la palabra. Nunca se llama a la red: `api` está sustituida.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api.js'
import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import { SettingsMenu } from './SettingsMenu.jsx'

function abrir() {
  return render(
    <LangProvider>
      <SettingsMenu
        onClose={() => {}}
        onOpenChime={() => {}}
        onOpenSnippets={() => {}}
        onOpenLinks={() => {}}
      />
    </LangProvider>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('Apagar el host', () => {
  it('sin la capacidad, el botón no aparece', async () => {
    const cap = vi
      .spyOn(api, 'capabilities')
      .mockResolvedValue({ host_poweroff: false, host_poweroff_word: null })
    abrir()
    await waitFor(() => expect(cap).toHaveBeenCalled())
    expect(screen.queryByText(en['poweroff.title'])).toBeNull()
  })

  it('si la consulta falla, tampoco aparece', async () => {
    const cap = vi.spyOn(api, 'capabilities').mockRejectedValue(new Error('x'))
    abrir()
    await waitFor(() => expect(cap).toHaveBeenCalled())
    expect(screen.queryByText(en['poweroff.title'])).toBeNull()
  })

  it('con la capacidad, pide la palabra y solo entonces envía', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue({
      host_poweroff: true,
      host_poweroff_word: 'APAGAR',
    })
    const apagar = vi.spyOn(api, 'hostPoweroff').mockResolvedValue({})
    abrir()

    fireEvent.click(await screen.findByText(en['poweroff.title']))
    const boton = screen.getByRole('button', { name: en['poweroff.confirm'] })
    expect(boton).toBeDisabled()

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'apag' } })
    expect(boton).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox'), { target: { value: ' apagar ' } })
    expect(boton).toBeEnabled()

    fireEvent.click(boton)
    await screen.findByText(en['poweroff.sent'])
    expect(apagar).toHaveBeenCalledTimes(1)
  })

  it('un fallo del servidor se enseña traducido y se puede reintentar', async () => {
    vi.spyOn(api, 'capabilities').mockResolvedValue({
      host_poweroff: true,
      host_poweroff_word: 'APAGAR',
    })
    const { ApiError } = await import('../api.js')
    vi.spyOn(api, 'hostPoweroff').mockRejectedValue(
      new ApiError(502, { code: 'err.host_poweroff_unreachable' }),
    )
    abrir()
    fireEvent.click(await screen.findByText(en['poweroff.title']))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'APAGAR' } })
    fireEvent.click(screen.getByRole('button', { name: en['poweroff.confirm'] }))

    await screen.findByText(en['err.host_poweroff_unreachable'])
  })
})
