import { useEffect, useState } from 'react'

import { api } from '../api.js'
import { useT } from '../i18n/index.jsx'
import { Modal } from './sidebar/Modal.jsx'
import { PencilIcon, TrashIcon } from './sidebar/icons.jsx'

/**
 * Enlaces generales del panel: título y URL.
 *
 * Son los que no pertenecen a ningún proyecto —el repositorio de todos, el
 * panel del proveedor, la documentación— y salen en el menú del eslabón de
 * cualquier terminal. Los del proyecto siguen viviendo en su formulario y se
 * pintan como badges en la cabecera de sus sesiones.
 *
 * Sin título se guarda el host de la URL, y sin esquema se asume `https`:
 * las dos cosas las decide el backend, que es quien valida.
 */
export function LinkSettings({ onClose, onChanged }) {
  const { t, tError } = useT()
  const [links, setLinks] = useState([])
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  // Id del enlace que se está editando; null = el formulario crea uno nuevo.
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState(null)

  const recargar = async () => {
    try {
      setLinks(await api.listLinks())
    } catch (err) {
      setError(tError(err))
    }
  }

  useEffect(() => {
    recargar()
    // Solo al abrir: recargar en cada render dejaría el formulario inútil.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const limpiar = () => {
    setEditing(null)
    setTitle('')
    setUrl('')
  }

  const guardar = async (e) => {
    e.preventDefault()
    if (!url.trim()) return
    try {
      if (editing) await api.updateLink(editing, title, url)
      else await api.createLink(title, url)
      setError(null)
      limpiar()
      await recargar()
      onChanged?.()
    } catch (err) {
      setError(tError(err))
    }
  }

  const borrar = async (id) => {
    try {
      await api.deleteLink(id)
      if (editing === id) limpiar()
      await recargar()
      onChanged?.()
    } catch (err) {
      setError(tError(err))
    }
  }

  return (
    <Modal title={t('links.title')} onClose={onClose} panelClassName="max-w-lg">
      <p className="mb-3 text-xs text-panel-muted">{t('links.help')}</p>

      <ul className="mb-4 divide-y divide-panel-border rounded border border-panel-border">
        {links.map((x) => (
          <li key={x.id} className="flex items-center gap-2 px-2 py-1.5">
            <span
              className="min-w-0 flex-1 truncate text-xs text-gray-100"
              title={x.url}
            >
              {x.title}
            </span>
            <button
              type="button"
              onClick={() => {
                setEditing(x.id)
                setTitle(x.title)
                setUrl(x.url)
              }}
              title={t('links.edit')}
              aria-label={t('links.edit')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
            >
              <PencilIcon />
            </button>
            <button
              type="button"
              onClick={() => borrar(x.id)}
              title={t('links.delete')}
              aria-label={t('links.delete')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-red-400"
            >
              <TrashIcon />
            </button>
          </li>
        ))}
        {links.length === 0 && (
          <li className="px-2 py-2 text-xs text-panel-muted">{t('links.empty')}</li>
        )}
      </ul>

      <form onSubmit={guardar} className="space-y-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('links.title_placeholder')}
          className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-panel-accent"
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={t('links.url_placeholder')}
          className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 font-mono text-xs text-gray-100 outline-none focus:border-panel-accent"
        />
        {error && <p className="text-xs text-red-400">{error}</p>}
        <div className="flex justify-end gap-2">
          {editing && (
            <button
              type="button"
              onClick={limpiar}
              className="rounded px-3 py-1.5 text-xs text-panel-muted transition hover:text-gray-100"
            >
              {t('links.cancel')}
            </button>
          )}
          <button
            type="submit"
            disabled={!url.trim()}
            className="rounded bg-panel-accent px-3 py-1.5 text-xs font-medium text-white transition disabled:opacity-40"
          >
            {editing ? t('links.save') : t('links.add')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
