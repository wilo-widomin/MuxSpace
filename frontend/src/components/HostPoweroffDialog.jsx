import { useState } from 'react'

import { api } from '../api.js'
import { useT } from '../i18n/index.jsx'
import { Modal } from './sidebar/Modal.jsx'

/**
 * Confirmación para apagar el ordenador host.
 *
 * Hay que escribir una palabra y el botón no se activa hasta que coincide:
 * un doble paso que se resuelve igual con ratón que con el teclado virtual de
 * una tableta. La palabra la manda el servidor (`/api/capabilities`) y él
 * también la vuelve a comprobar; aquí solo evita el envío por descuido. No
 * distingue mayúsculas porque un teclado virtual las pone o no a su gusto.
 */
export function HostPoweroffDialog({ word, onClose }) {
  const { t, tError } = useT()
  const [typed, setTyped] = useState('')
  const [state, setState] = useState('idle') // idle | sending | sent
  const [error, setError] = useState(null)

  const matches = typed.trim().toLowerCase() === (word || '').toLowerCase()

  const submit = async (e) => {
    e.preventDefault()
    if (!matches || state !== 'idle') return
    setState('sending')
    setError(null)
    try {
      await api.hostPoweroff(typed)
      setState('sent')
    } catch (err) {
      setError(err)
      setState('idle')
    }
  }

  return (
    <Modal title={t('poweroff.title')} onClose={onClose}>
      {state === 'sent' ? (
        <p role="status" className="text-sm text-gray-100">
          {t('poweroff.sent')}
        </p>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <p className="rounded bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {t('poweroff.warning')}
          </p>
          <label className="block text-xs text-gray-100">
            {t('poweroff.type_word', { word })}
            <input
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              autoCapitalize="characters"
              autoCorrect="off"
              spellCheck={false}
              className="mt-1 block w-full rounded border border-panel-border bg-panel-bg px-3 py-2 text-sm text-gray-100"
            />
          </label>
          {error && <p className="text-xs text-red-400">{tError(error)}</p>}
          <button
            type="submit"
            disabled={!matches || state !== 'idle'}
            className="w-full rounded bg-red-500 px-3 py-3 text-sm font-medium text-white transition enabled:hover:bg-red-600 disabled:opacity-40"
          >
            {state === 'sending' ? t('poweroff.sending') : t('poweroff.confirm')}
          </button>
        </form>
      )}
    </Modal>
  )
}
