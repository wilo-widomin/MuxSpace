import React, { useState } from 'react'
import { useT } from '../i18n/index.jsx'

// Pantalla de inicio de sesión (HTTP Basic). Las credenciales se
// validan haciendo una petición real a /api/sessions.
export default function LoginScreen({ onSubmit, error }) {
  const { t } = useT()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

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
        <p className="mb-5 text-sm text-panel-muted">
          {t('login.subtitle')}
        </p>

        <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
          {t('login.username')}
        </label>
        <input
          className="mb-4 w-full rounded border border-panel-border bg-panel-bg px-3 py-2 text-sm outline-none focus:border-panel-accent"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          autoComplete="username"
        />

        <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
          {t('login.password')}
        </label>
        <input
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
