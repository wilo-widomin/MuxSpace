import { useEffect, useState } from 'react'

import { ApiError, api } from '../../api.js'
import { useT } from '../../i18n/index.jsx'
import { quotePath } from '../../lib/paths.js'
import { DirBrowserModal } from './DirBrowserModal.jsx'
import { FolderIcon } from './Modal.jsx'
import { SectionCaret } from './SectionCaret.jsx'

// Carpeta a la que se sube mientras nadie elija otra.
const DEFAULT_DIR = '~/tmp'

// Última carpeta elegida, POR ESPACIO. En localStorage y no en sessionStorage
// —a diferencia del espacio activo, que es de cada pestaña— porque el destino
// de las subidas de un espacio es una preferencia que dura, no algo que se
// decida otra vez en cada pestaña.
const DIR_KEY = 'muxspace:upload-dir'
const dirKeyOf = (space) => `${DIR_KEY}:${space || 'unassigned'}`

/** Carpeta recordada para `space`, o `null` si no hay ninguna. */
function readSavedDir(space) {
  try {
    return localStorage.getItem(dirKeyOf(space)) || null
  } catch {
    return null // sin localStorage: se usa la de por defecto y no se recuerda
  }
}

function saveDir(space, dir) {
  try {
    localStorage.setItem(dirKeyOf(space), dir)
  } catch {
    /* sin localStorage: el destino vale para esta sesión y nada más */
  }
}

// Subir archivos a una carpeta que el usuario elige con un navegador tipo
// explorador (DirBrowserModal). A diferencia de "pegar imagen", el destino
// es una carpeta REAL del usuario y los archivos no se borran nunca: solo
// guardamos el historial de las últimas 5 subidas para recopiar su ruta.
//
// El destino se recuerda por espacio: cada uno suele tener su carpeta de
// trabajo, y volver a elegirla a mano cada vez que se cambia de espacio era
// el trabajo que este panel existe para ahorrar.
export function UploadFiles({ open, onToggle, space }) {
  const { t, tError } = useT()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [uploads, setUploads] = useState([]) // [{ name, path, dir }], la más nueva primero
  const [destDir, setDestDir] = useState(null) // carpeta destino elegida (~/...)
  const [browserOpen, setBrowserOpen] = useState(false)
  const [selectedPath, setSelectedPath] = useState(null)
  const [copied, setCopied] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  async function refreshUploads() {
    try {
      setUploads(await api.listUploads())
    } catch {
      // No crítico: si falla el historial, dejamos la lista como estaba.
    }
  }

  // Al abrir: el historial de subidas.
  useEffect(() => {
    if (!open) return
    refreshUploads()
  }, [open])

  // Destino: el que este espacio tenga recordado y, si no, `~/tmp`.
  //
  // No se da por bueno sin más: se le pregunta al backend, que es quien sabe
  // si esa carpeta existe y sigue dentro de las raíces permitidas. Una
  // carpeta borrada desde la última vez —o un `~/tmp` que no exista— caería
  // en un destino inválido y la subida fallaría en el peor momento, con el
  // archivo ya elegido. Si no vale, se cae a la primera raíz configurada.
  useEffect(() => {
    if (!open) return
    let cancelado = false
    const guardada = readSavedDir(space)
    api
      .dirBrowse(guardada || DEFAULT_DIR)
      .catch(() => api.dirBrowse(''))
      .then((r) => {
        // Cambiar de espacio mientras la respuesta viaja dejaría el destino
        // del espacio anterior pintado en el nuevo.
        if (!cancelado) setDestDir(r.path)
      })
      .catch(() => {})
    return () => {
      cancelado = true
    }
  }, [open, space])

  async function doUpload(file) {
    if (!file) return
    if (!destDir) {
      setError(t('upload.no_dir'))
      return
    }
    setError(null)
    setBusy(true)
    try {
      const res = await api.uploadFile(file, destDir)
      await refreshUploads()
      copyToClipboard(res.path)
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.upload_failed'))
    } finally {
      setBusy(false)
    }
  }

  function handleFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    doUpload(file)
  }

  // Arrastrar y soltar un archivo sobre la zona de subida.
  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer?.files?.[0]
    if (file) doUpload(file)
  }

  async function handleRemove(u) {
    try {
      setUploads(await api.deleteUpload(u.path))
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.remove_failed'))
      return
    }
    if (u.path === selectedPath) {
      setSelectedPath(null)
      setCopied(false)
    }
  }

  // Copia una ruta al portapapeles y la marca como seleccionada (mismo apaño
  // con respaldo a execCommand que en "pegar imagen").
  async function copyToClipboard(path) {
    setSelectedPath(path)
    try {
      await navigator.clipboard.writeText(quotePath(path))
      setCopied(true)
      return
    } catch {
      /* sin Clipboard API: respaldo abajo */
    }
    try {
      const ta = document.createElement('textarea')
      ta.value = quotePath(path)
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <div className="shrink-0 border-t border-panel-border px-4 py-3">
        <button
          onClick={onToggle}
          className="flex w-full items-center justify-between text-xs uppercase tracking-wide text-panel-muted transition hover:text-gray-100"
        >
          <span>{t('upload.title')}</span>
          <SectionCaret open={open} />
        </button>
        {open && (
          <div className="mt-2">
            <p className="text-xs text-panel-muted">{t('upload.dest_label')}</p>
            <div className="mt-1 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-black/30 px-1.5 py-1 text-[11px] text-gray-200">
                {destDir || '—'}
              </code>
              <button
                onClick={() => setBrowserOpen(true)}
                title={t('upload.choose_dir')}
                className="flex shrink-0 items-center gap-1 rounded border border-panel-border px-2 py-1 text-xs text-panel-muted transition hover:border-panel-accent hover:text-gray-100"
              >
                <FolderIcon />
                {t('upload.choose_dir')}
              </button>
            </div>

            <label
              onDragOver={(e) => {
                e.preventDefault()
                if (!busy) setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              className={`mt-2 flex cursor-pointer items-center justify-center rounded border border-dashed px-2 py-3 text-center text-xs transition ${
                dragOver
                  ? 'border-panel-accent bg-panel-accent/10 text-gray-100'
                  : 'border-panel-border text-panel-muted hover:border-panel-accent hover:text-gray-100'
              }`}
            >
              {busy
                ? t('upload.uploading')
                : dragOver
                  ? t('upload.drop_here')
                  : t('upload.dropzone')}
              <input
                type="file"
                onChange={handleFile}
                disabled={busy}
                className="hidden"
              />
            </label>
            {error && <p className="mt-1 text-xs text-red-400">{error}</p>}

            {uploads.length > 0 && (
              <>
                <p className="mt-2 text-xs text-panel-muted">{t('upload.recent')}</p>
                <ul className="mt-1 space-y-1">
                  {uploads.map((u) => {
                    const sel = u.path === selectedPath
                    return (
                      <li
                        key={u.path}
                        className={`group flex items-center gap-1 rounded border px-1.5 py-1 transition ${
                          sel
                            ? 'border-panel-accent'
                            : 'border-panel-border hover:border-panel-accent'
                        }`}
                      >
                        <button
                          onClick={() => copyToClipboard(u.path)}
                          title={u.path}
                          className="min-w-0 flex-1 text-left"
                        >
                          <span className="block truncate text-xs text-gray-100">
                            {u.name}
                          </span>
                          <span className="block truncate text-[10px] text-panel-muted">
                            {quotePath(u.path)}
                          </span>
                        </button>
                        <button
                          onClick={() => handleRemove(u)}
                          title={t('upload.remove')}
                          aria-label={t('upload.remove_aria', { name: u.name })}
                          className="hidden h-5 w-5 shrink-0 items-center justify-center rounded-full border border-panel-border bg-panel-surface text-sm leading-none text-gray-200 transition hover:bg-red-600 hover:text-white group-hover:flex"
                        >
                          ×
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}

            {selectedPath && (
              <div className="mt-2 rounded border border-panel-border bg-panel-bg p-2">
                <p className="text-xs text-panel-muted">
                  {copied ? t('upload.copied') : t('upload.copy_hint')}
                </p>
                <code
                  onClick={() => copyToClipboard(selectedPath)}
                  title={t('upload.copy_path')}
                  className="mt-1 block cursor-pointer break-all rounded bg-black/30 px-1.5 py-1 text-[11px] leading-snug text-green-300 transition hover:bg-black/50"
                >
                  {quotePath(selectedPath)}
                </code>
              </div>
            )}
          </div>
        )}
      </div>

      {browserOpen && (
        <DirBrowserModal
          initialPath={destDir || ''}
          onClose={() => setBrowserOpen(false)}
          onPick={(path) => {
            setDestDir(path)
            saveDir(space, path)
            setBrowserOpen(false)
          }}
        />
      )}
    </>
  )
}
