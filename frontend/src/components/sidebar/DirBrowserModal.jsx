import { useEffect, useState } from 'react'

import { ApiError, api } from '../../api.js'
import { useT } from '../../i18n/index.jsx'
import { CloseIcon, FolderIcon, Modal } from './Modal.jsx'

// Navegador de carpetas tipo explorador: entra en subcarpetas con clic, sube
// un nivel, crea carpetas nuevas y confirma el destino con "Guardar aquí".
// Solo se mueve dentro de las raíces configuradas en el backend.
export function DirBrowserModal({ initialPath, onClose, onPick }) {
  const { t, tError } = useT()
  const [cur, setCur] = useState(initialPath || '')
  const [parent, setParent] = useState(null)
  const [dirs, setDirs] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  async function load(path) {
    setBusy(true)
    setError(null)
    try {
      const r = await api.dirBrowse(path)
      setCur(r.path)
      setParent(r.parent)
      setDirs(r.dirs)
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.browse_failed'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load(initialPath || '')
    // Solo al montar: la navegación posterior la disparan los clics.
  }, [])

  async function submitNewFolder(e) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.dirCreate(cur, name)
      setCreating(false)
      setNewName('')
      await load(r.path) // entramos en la carpeta recién creada
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.create_failed'))
      setBusy(false)
    }
  }

  return (
    <Modal title={t('upload.browser_title')} onClose={onClose} panelClassName="max-w-lg">
      <div className="flex items-center gap-2">
        <button
          onClick={() => parent !== null && load(parent)}
          disabled={parent === null || busy}
          title={t('upload.up')}
          className="shrink-0 rounded border border-panel-border px-2 py-1 text-sm text-panel-muted transition enabled:hover:border-panel-accent enabled:hover:text-gray-100 disabled:opacity-40"
        >
          ↰
        </button>
        <code className="min-w-0 flex-1 truncate rounded bg-black/30 px-2 py-1 text-xs text-gray-200">
          {cur || '—'}
        </code>
      </div>

      <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto">
        {dirs.length === 0 && !busy && (
          <li className="px-2 py-1 text-xs text-panel-muted">
            {t('upload.empty_dir')}
          </li>
        )}
        {dirs.map((d) => (
          <li key={d}>
            <button
              onClick={() => load(d)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-gray-100 transition hover:bg-panel-bg"
            >
              <span className="shrink-0 text-panel-muted">
                <FolderIcon />
              </span>
              <span className="min-w-0 truncate">{d.split('/').pop() || d}</span>
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}

      <div className="mt-3 border-t border-panel-border pt-3">
        {creating ? (
          <form onSubmit={submitNewFolder} className="flex items-center gap-2">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t('upload.new_folder_name')}
              className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-xs text-gray-100 outline-none focus:border-panel-accent"
            />
            <button
              type="submit"
              disabled={busy || !newName.trim()}
              className="shrink-0 rounded bg-panel-accent px-2 py-1 text-xs text-white transition disabled:opacity-40"
            >
              {t('upload.create')}
            </button>
            <button
              type="button"
              onClick={() => {
                setCreating(false)
                setNewName('')
              }}
              className="shrink-0 rounded border border-panel-border px-2 py-1 text-xs text-panel-muted transition hover:text-gray-100"
            >
              {t('modal.close')}
            </button>
          </form>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <button
              onClick={() => setCreating(true)}
              disabled={busy}
              className="rounded border border-panel-border px-2 py-1 text-xs text-panel-muted transition hover:border-panel-accent hover:text-gray-100 disabled:opacity-40"
            >
              + {t('upload.new_folder')}
            </button>
            <button
              onClick={() => onPick(cur)}
              disabled={busy || !cur}
              className="rounded bg-panel-accent px-3 py-1 text-xs font-medium text-white transition disabled:opacity-40"
            >
              {t('upload.save_here')}
            </button>
          </div>
        )}
      </div>
    </Modal>
  )
}
