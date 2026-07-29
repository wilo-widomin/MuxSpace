import { useState } from 'react'

import { useT } from '../../i18n/index.jsx'
import { UNASSIGNED, spaceKeyOf } from '../../spaces.js'
import { CheckIcon, PencilIcon, PlusIcon, TrashIcon } from './icons.jsx'
// `CloseIcon` vive en `Modal.jsx` desde antes de esta extracción; ver el
// comentario de `icons.jsx` sobre por qué no se ha movido también.
import { CloseIcon } from './Modal.jsx'

// <input> de directorio con autocompletado: mientras el usuario escribe
// (o al ganar el foco) pide al backend las subcarpetas que coinciden con el
// prefijo bajo las raíces configuradas (ver `MUXSPACE_DIR_SUGGESTION_ROOTS`
// y el endpoint /api/dir-suggestions). Las muestra en un <datalist> nativo.
// Barra de espacios: elige cuál mira ESTA pestaña y permite crear,
// renombrar y borrar. Dos entradas del selector no son espacios reales:
// «Todas» (vista sin filtrar) y «Sin asignar» (las sesiones que no están
// en ningún espacio, p. ej. las creadas fuera del panel); por eso ninguna
// se puede renombrar ni borrar.
export function SpacesBar({
  spaces,
  sessions,
  activeSpace,
  onSetActiveSpace,
  onCreateSpace,
  onRenameSpace,
  onDeleteSpace,
}) {
  const { t, tError } = useT()
  // `mode` es null (solo el selector), 'create' o 'rename': el formulario
  // sustituye a la barra en vez de abrir un modal, que para un solo campo
  // resultaría desproporcionado.
  const [mode, setMode] = useState(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const current = spaces.find((s) => s.id === activeSpace)
  const editable = Boolean(current)

  const counts = new Map()
  for (const s of sessions) {
    const key = spaceKeyOf(s)
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  const countOf = (key) => counts.get(key) || 0

  const open = (nextMode) => {
    setMode(nextMode)
    setValue(nextMode === 'rename' && current ? current.title : '')
    setError(null)
  }

  const close = () => {
    setMode(null)
    setValue('')
    setError(null)
  }

  const submit = async (e) => {
    e.preventDefault()
    const title = value.trim()
    if (!title) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'create') {
        const created = await onCreateSpace(title)
        // Saltamos al espacio recién creado: crearlo y quedarte donde
        // estabas obligaría a buscarlo en el selector.
        if (created?.id) onSetActiveSpace(created.id)
      } else if (current) {
        await onRenameSpace(current.id, title)
      }
      close()
    } catch (err) {
      setError(tError(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!current) return
    const n = countOf(current.id)
    // Dos claves completas (con sus saltos de línea) en vez de trozos
    // concatenados: el plural y la concordancia son cosa de cada idioma.
    const ok = window.confirm(
      n > 0
        ? t('spaces.confirm_delete', { title: current.title, count: n })
        : t('spaces.confirm_delete_empty', { title: current.title }),
    )
    if (!ok) return
    setBusy(true)
    try {
      await onDeleteSpace(current.id)
    } catch (err) {
      setError(tError(err))
    } finally {
      setBusy(false)
    }
  }

  if (mode) {
    return (
      <div className="border-b border-panel-border px-3 py-2">
        <p className="mb-1 text-xs text-panel-muted">{t('spaces.title')}</p>
        <form onSubmit={submit} className="flex items-center gap-1">
          <input
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') close()
            }}
            placeholder={
              mode === 'create'
                ? t('spaces.create_placeholder')
                : t('spaces.rename_placeholder')
            }
            className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-sm outline-none focus:border-panel-accent"
          />
          <button
            type="submit"
            disabled={busy || !value.trim()}
            title={t('spaces.save')}
            className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-surface hover:text-green-400 disabled:opacity-40"
          >
            <CheckIcon />
          </button>
          <button
            type="button"
            onClick={close}
            title={t('spaces.cancel')}
            className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-surface hover:text-gray-100"
          >
            <CloseIcon />
          </button>
        </form>
        {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
      </div>
    )
  }

  return (
    <div className="border-b border-panel-border px-3 py-2">
      <p className="mb-1 text-xs text-panel-muted">{t('spaces.title')}</p>
      <div className="flex items-center gap-1">
        <select
          value={activeSpace}
          onChange={(e) => onSetActiveSpace(e.target.value)}
          title={t('spaces.select_title')}
          className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-sm text-gray-100 outline-none focus:border-panel-accent"
        >
          <option value={UNASSIGNED}>
            {t('spaces.option', {
              title: t('spaces.unassigned'),
              count: countOf(UNASSIGNED),
            })}
          </option>
          {spaces.map((s) => (
            <option key={s.id} value={s.id}>
              {/* El título lo puso el usuario: no se traduce, solo se
                  compone con el contador. */}
              {t('spaces.option', { title: s.title, count: countOf(s.id) })}
            </option>
          ))}
        </select>
        <button
          onClick={() => open('create')}
          title={t('spaces.new')}
          className="shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
        >
          <PlusIcon />
        </button>
        <button
          onClick={() => open('rename')}
          disabled={!editable}
          title={
            editable ? t('spaces.rename') : t('spaces.rename_disabled')
          }
          className="shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <PencilIcon />
        </button>
        <button
          onClick={remove}
          disabled={!editable || busy}
          title={
            editable ? t('spaces.delete') : t('spaces.delete_disabled')
          }
          className="shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-red-500/20 hover:text-red-400 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-panel-muted"
        >
          <TrashIcon />
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  )
}
