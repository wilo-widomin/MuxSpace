import React, { useEffect, useId, useRef, useState } from 'react'
import { useT } from '../i18n/index.jsx'

// Lo que tarda el campo Usuario en dejar de ser de solo lectura aunque nadie
// lo toque (por si el primer gesto es de un lector de pantallas, que no genera
// eventos de teclado ni de puntero en la página). Chrome decide si abre el
// desplegable de contraseñas guardadas en el instante de enfocar, así que
// basta con que el campo sea de solo lectura durante ese instante.
export const AUTOFOCUS_LOCK_MS = 300

// Pantalla de inicio de sesión (HTTP Basic). Las credenciales se
// validan haciendo una petición real a /api/sessions.
export default function LoginScreen({ onSubmit, error }) {
  const { t } = useT()
  // Prefijo de los `id` que atan cada etiqueta con su campo. Ver el comentario
  // equivalente en `Sidebar.jsx`.
  const uid = useId()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const usernameRef = useRef(null)

  // Foco automático sin desplegable de contraseñas: se enfoca el campo estando
  // `readOnly` (Chrome no ofrece las guardadas a un campo que no se puede
  // editar) y se libera con el primer gesto del usuario o pasado un instante.
  // Se toca el DOM directamente, no un estado: la liberación tiene que ser
  // síncrona para que la primera tecla pulsada ya entre en el campo.
  useEffect(() => {
    const input = usernameRef.current
    if (!input) return undefined
    input.readOnly = true
    input.focus()
    const unlock = () => {
      input.readOnly = false
    }
    const timer = setTimeout(unlock, AUTOFOCUS_LOCK_MS)
    return () => {
      clearTimeout(timer)
      unlock()
    }
  }, [])

  // El primer gesto del usuario libera el campo antes de que él actúe sobre él.
  const unlockOnGesture = (e) => {
    e.currentTarget.readOnly = false
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      await onSubmit(username, password)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-panel-bg text-gray-100">
      <form
        onSubmit={handleSubmit}
        className="w-80 rounded-lg border border-panel-border bg-panel-surface p-6 shadow-xl"
      >
        <h1 className="mb-1 text-xl font-semibold">{t('app.brand')}</h1>
        <p className="mb-5 text-sm text-panel-muted">{t('login.subtitle')}</p>

        <label
          htmlFor={`${uid}-usuario`}
          className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
        >
          {t('login.username')}
        </label>
        <input
          id={`${uid}-usuario`}
          className="mb-4 w-full rounded border border-panel-border bg-panel-bg px-3 py-2 text-sm outline-none focus:border-panel-accent"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          ref={usernameRef}
          onKeyDown={unlockOnGesture}
          onPointerDown={unlockOnGesture}
          onTouchStart={unlockOnGesture}
          autoComplete="username"
        />

        <label
          htmlFor={`${uid}-password`}
          className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
        >
          {t('login.password')}
        </label>
        <input
          id={`${uid}-password`}
          type="password"
          className="mb-4 w-full rounded border border-panel-border bg-panel-bg px-3 py-2 text-sm outline-none focus:border-panel-accent"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {error && (
          <p className="mb-4 rounded bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-panel-accent px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-600 disabled:opacity-50"
        >
          {submitting ? t('login.submitting') : t('login.submit')}
        </button>
      </form>
    </div>
  )
}
