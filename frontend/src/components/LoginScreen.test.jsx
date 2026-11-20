// Pantalla de login: el campo Usuario nace con el foco pero de solo lectura
// (para que Chrome no abra el desplegable de contraseñas guardadas) y se libera
// con el primer gesto o pasado un instante. Nunca debe quedarse bloqueado.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import LoginScreen, { AUTOFOCUS_LOCK_MS } from './LoginScreen.jsx'

function abrir(onSubmit = vi.fn()) {
  render(
    <LangProvider>
      <LoginScreen onSubmit={onSubmit} error={null} />
    </LangProvider>,
  )
  return { onSubmit, usuario: screen.getByLabelText(en['login.username']) }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('LoginScreen: foco sin desplegable', () => {
  it('el campo Usuario nace enfocado y de solo lectura', () => {
    const { usuario } = abrir()
    expect(document.activeElement).toBe(usuario)
    expect(usuario.readOnly).toBe(true)
  })

  it('la primera tecla lo libera antes de que entre el carácter', () => {
    const { usuario } = abrir()
    fireEvent.keyDown(usuario, { key: 'a' })
    expect(usuario.readOnly).toBe(false)
  })

  it('un clic lo libera', () => {
    const { usuario } = abrir()
    fireEvent.pointerDown(usuario)
    expect(usuario.readOnly).toBe(false)
  })

  it('un toque lo libera', () => {
    const { usuario } = abrir()
    fireEvent.touchStart(usuario)
    expect(usuario.readOnly).toBe(false)
  })

  it('sin tocar nada se libera solo, para no bloquear a un lector de pantalla', () => {
    const { usuario } = abrir()
    act(() => vi.advanceTimersByTime(AUTOFOCUS_LOCK_MS + 1))
    expect(usuario.readOnly).toBe(false)
    expect(document.activeElement).toBe(usuario)
  })

  it('se puede teclear y el formulario se envía', () => {
    const { usuario, onSubmit } = abrir()
    fireEvent.keyDown(usuario, { key: 'w' })
    fireEvent.change(usuario, { target: { value: 'willy' } })
    fireEvent.change(screen.getByLabelText(en['login.password']), {
      target: { value: 'x' },
    })
    fireEvent.submit(usuario.closest('form'))
    expect(onSubmit).toHaveBeenCalledWith('willy', 'x')
  })
})
