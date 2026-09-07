// El menú de Ajustes: la puerta única a las preferencias del panel entero.
//
// Lo que se prueba es que están las tres y que el idioma se cambia AHÍ, que
// es lo que justifica haberlo sacado del pie del sidebar.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import { SettingsMenu } from './SettingsMenu.jsx'

afterEach(cleanup)

function abrir(props = {}) {
  return render(
    <LangProvider>
      <SettingsMenu
        onClose={() => {}}
        onOpenChime={() => {}}
        onOpenSnippets={() => {}}
        onOpenLinks={() => {}}
        {...props}
      />
    </LangProvider>,
  )
}

describe('Menú de ajustes', () => {
  it('ofrece campanilla, textos rápidos, enlaces e idioma', () => {
    abrir()

    expect(screen.getByText(en['chime.title'])).toBeInTheDocument()
    expect(screen.getByText(en['snippets.title'])).toBeInTheDocument()
    expect(screen.getByText(en['links.title'])).toBeInTheDocument()
    expect(screen.getByLabelText(en['lang.label'])).toBeInTheDocument()
  })

  it('cada fila abre su diálogo', () => {
    const chime = vi.fn()
    const snippets = vi.fn()
    abrir({ onOpenChime: chime, onOpenSnippets: snippets })

    fireEvent.click(screen.getByText(en['chime.title']))
    fireEvent.click(screen.getByText(en['snippets.title']))

    expect(chime).toHaveBeenCalled()
    expect(snippets).toHaveBeenCalled()
  })

  it('el idioma se cambia desde aquí y la interfaz lo obedece', () => {
    abrir()

    fireEvent.change(screen.getByLabelText(en['lang.label']), {
      target: { value: 'es' },
    })

    expect(screen.getByText(es['snippets.title'])).toBeInTheDocument()
  })
})
