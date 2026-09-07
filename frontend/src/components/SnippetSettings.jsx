import { useEffect, useState } from 'react'

import { api } from '../api.js'
import { useT } from '../i18n/index.jsx'
import { Modal } from './sidebar/Modal.jsx'
import { PencilIcon, TrashIcon } from './sidebar/icons.jsx'

/**
 * Textos rápidos: lo que se escribe en la terminal sin ejecutarlo.
 *
 * POR QUÉ EXISTE: desde una tableta, teclear `/code-review high` o el nombre
 * exacto de una skill cuesta más que todo lo demás junto, y no es un comando
 * de shell —es texto para el programa que ya corre dentro—. Un Comando de la
 * biblioteca no sirve: ese abre una terminal y ejecuta.
 *
 * El texto se guarda con saltos de línea incluidos, y quien lo inserta es el
 * navegador (`term.paste`), así que llega tal cual y NO se envía: queda en
 * el prompt para revisarlo y pulsar Enter a mano.
 */
export function SnippetSettings({ onClose, onChanged }) {
  const { t, tError } = useT()
  const [snippets, setSnippets] = useState([])
  const [label, setLabel] = useState('')
  const [text, setText] = useState('')
  // Id del texto que se está editando; null = el formulario crea uno nuevo.
  const [editing, setEditing] = useState(null)
  const [error, setError] = useState(null)

  const recargar = async () => {
    try {
      setSnippets(await api.listSnippets())
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
    setLabel('')
    setText('')
  }

  const guardar = async (e) => {
    e.preventDefault()
    if (!text.trim()) return
    try {
      if (editing) await api.updateSnippet(editing, label, text)
      else await api.createSnippet(label, text)
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
      await api.deleteSnippet(id)
      if (editing === id) limpiar()
      await recargar()
      onChanged?.()
    } catch (err) {
      setError(tError(err))
    }
  }

  return (
    <Modal title={t('snippets.title')} onClose={onClose} panelClassName="max-w-lg">
      <p className="mb-3 text-xs text-panel-muted">{t('snippets.help')}</p>

      <ul className="mb-4 divide-y divide-panel-border rounded border border-panel-border">
        {snippets.map((s) => (
          <li key={s.id} className="flex items-center gap-2 px-2 py-1.5">
            <span
              className="min-w-0 flex-1 truncate text-xs text-gray-100"
              title={s.text}
            >
              {s.label}
            </span>
            <button
              type="button"
              onClick={() => {
                setEditing(s.id)
                setLabel(s.label)
                setText(s.text)
              }}
              title={t('snippets.edit')}
              aria-label={t('snippets.edit')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
            >
              <PencilIcon />
            </button>
            <button
              type="button"
              onClick={() => borrar(s.id)}
              title={t('snippets.delete')}
              aria-label={t('snippets.delete')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-red-400"
            >
              <TrashIcon />
            </button>
          </li>
        ))}
        {snippets.length === 0 && (
          <li className="px-2 py-2 text-xs text-panel-muted">{t('snippets.empty')}</li>
        )}
      </ul>

      <form onSubmit={guardar} className="space-y-2">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={t('snippets.label_placeholder')}
          className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-panel-accent"
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('snippets.text_placeholder')}
          rows={3}
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
              {t('snippets.cancel')}
            </button>
          )}
          <button
            type="submit"
            disabled={!text.trim()}
            className="rounded bg-panel-accent px-3 py-1.5 text-xs font-medium text-white transition disabled:opacity-40"
          >
            {editing ? t('snippets.save') : t('snippets.add')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
