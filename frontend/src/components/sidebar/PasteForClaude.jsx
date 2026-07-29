import { useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../../api.js'
import { useT } from '../../i18n/index.jsx'
import { quotePath } from '../../lib/paths.js'
import { SectionCaret } from './SectionCaret.jsx'

// Caja "Pegar imagen para Claude": apaño para compartir capturas. El usuario
// hace clic en el área y pega (Ctrl+V); la imagen se sube al backend, que la
// guarda en disco. Debajo se muestra una tira con las últimas capturas (el
// backend conserva solo las 5 más recientes): al hacer clic en cualquiera se
// copia su ruta absoluta para poder dársela a Claude. También admite elegir
// un fichero.
export function PasteForClaude({ open, onToggle }) {
  const { t, tError } = useT()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [pastes, setPastes] = useState([]) // [{ filename, path }], la más nueva primero
  const [selectedPath, setSelectedPath] = useState(null)
  const [copied, setCopied] = useState(false)
  const [zoom, setZoom] = useState(null) // captura ampliada en el visor: { filename, path } | null
  const areaRef = useRef(null)
  const stripRef = useRef(null)

  // Cierra el visor ampliado con Escape.
  useEffect(() => {
    if (!zoom) return
    const onKey = (e) => {
      if (e.key === 'Escape') setZoom(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoom])

  // Desplaza la tira de miniaturas a izquierda (-1) o derecha (+1).
  function scrollStrip(dir) {
    stripRef.current?.scrollBy({ left: dir * 140, behavior: 'smooth' })
  }

  async function refreshList() {
    try {
      setPastes(await api.listPastes())
    } catch {
      // No crítico: si falla la lista, dejamos la tira como estaba.
    }
  }

  // Al abrir la sección, cargamos las capturas que ya hay en disco (para poder
  // re-elegir una incluso tras recargar la página).
  useEffect(() => {
    if (open) refreshList()
  }, [open])

  async function uploadBlob(blob) {
    setError(null)
    setBusy(true)
    try {
      const res = await api.pasteImage(blob)
      await refreshList()
      // La recién subida pasa a estar seleccionada y copiada al portapapeles.
      copyToClipboard(res.path)
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('paste.upload_failed'))
    } finally {
      setBusy(false)
    }
  }

  function handlePaste(e) {
    const items = e.clipboardData?.items || []
    for (const it of items) {
      if (it.type && it.type.startsWith('image/')) {
        const blob = it.getAsFile()
        if (blob) {
          e.preventDefault()
          uploadBlob(blob)
          return
        }
      }
    }
    // Sin imagen: evitamos que el texto pegado quede en el textarea.
    e.preventDefault()
    if (areaRef.current) areaRef.current.value = ''
    setError(t('paste.no_image_in_clipboard'))
  }

  function handleFile(e) {
    const f = e.target.files?.[0]
    if (f) uploadBlob(f)
    e.target.value = ''
  }

  async function handleDelete(p) {
    try {
      await api.deletePaste(p.filename)
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('paste.delete_failed'))
      return
    }
    // Si borramos la que estaba seleccionada, limpiamos la ruta mostrada.
    if (p.path === selectedPath) {
      setSelectedPath(null)
      setCopied(false)
    }
    refreshList()
  }

  // Copia una ruta al portapapeles y la marca como seleccionada.
  // navigator.clipboard requiere contexto seguro (el panel va por https/mTLS,
  // así que está disponible); si no, cae a execCommand con un input temporal.
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
          <span>{t('paste.title')}</span>
          <SectionCaret open={open} />
        </button>
        {open && (
          <div className="mt-2">
            <textarea
              ref={areaRef}
              onPaste={handlePaste}
              rows={2}
              spellCheck={false}
              placeholder={busy ? t('paste.uploading') : t('paste.placeholder')}
              className="w-full resize-none rounded border border-dashed border-panel-border bg-panel-bg px-2 py-1.5 text-xs text-gray-100 outline-none focus:border-panel-accent"
            />
            <label className="mt-1 inline-block cursor-pointer text-xs text-panel-muted transition hover:text-gray-100">
              {t('paste.choose_file')}
              <input
                type="file"
                accept="image/*"
                onChange={handleFile}
                className="hidden"
              />
            </label>
            {error && <p className="mt-1 text-xs text-red-400">{error}</p>}

            {pastes.length > 0 && (
              <>
                <p className="mt-2 text-xs text-panel-muted">{t('paste.recent')}</p>
                <div className="mt-1 flex items-center gap-1">
                  <button
                    onClick={() => scrollStrip(-1)}
                    title={t('paste.prev')}
                    aria-label={t('paste.scroll_left')}
                    className="shrink-0 rounded px-1 py-2 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
                  >
                    ‹
                  </button>
                  <div
                    ref={stripRef}
                    className="flex flex-nowrap gap-2 overflow-x-auto py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                  >
                    {pastes.map((p) => {
                      const sel = p.path === selectedPath
                      return (
                        <div key={p.filename} className="group relative shrink-0">
                          <button
                            onClick={() => copyToClipboard(p.path)}
                            title={p.filename}
                            className={`block overflow-hidden rounded border transition ${
                              sel
                                ? 'border-panel-accent ring-1 ring-panel-accent'
                                : 'border-panel-border hover:border-panel-accent'
                            }`}
                          >
                            <img
                              src={api.pasteThumbUrl(p.filename)}
                              alt={p.filename}
                              className="h-14 w-14 object-cover"
                            />
                          </button>
                          <button
                            onClick={() => setZoom(p)}
                            title={t('paste.zoom')}
                            aria-label={t('paste.zoom_aria', { name: p.filename })}
                            className="absolute -left-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full border border-panel-border bg-panel-surface text-gray-200 shadow transition hover:bg-panel-accent hover:text-white group-hover:flex"
                          >
                            <EyeIcon />
                          </button>
                          <button
                            onClick={() => handleDelete(p)}
                            title={t('paste.delete')}
                            aria-label={t('paste.delete_aria', {
                              name: p.filename,
                            })}
                            className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full border border-panel-border bg-panel-surface text-sm leading-none text-gray-200 shadow transition hover:bg-red-600 hover:text-white group-hover:flex"
                          >
                            ×
                          </button>
                        </div>
                      )
                    })}
                  </div>
                  <button
                    onClick={() => scrollStrip(1)}
                    title={t('paste.next')}
                    aria-label={t('paste.scroll_right')}
                    className="shrink-0 rounded px-1 py-2 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
                  >
                    ›
                  </button>
                </div>
              </>
            )}

            {selectedPath && (
              <div className="mt-2 rounded border border-panel-border bg-panel-bg p-2">
                <p className="text-xs text-panel-muted">
                  {copied ? t('paste.copied') : t('paste.copy_hint')}
                </p>
                <code
                  onClick={() => copyToClipboard(selectedPath)}
                  title={t('paste.copy_path')}
                  className="mt-1 block cursor-pointer break-all rounded bg-black/30 px-1.5 py-1 text-[11px] leading-snug text-green-300 transition hover:bg-black/50"
                >
                  {quotePath(selectedPath)}
                </code>
              </div>
            )}
          </div>
        )}
      </div>

      {zoom && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setZoom(null)}
        >
          <div
            className="relative flex max-h-[90vh] max-w-[90vw] flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={api.pasteThumbUrl(zoom.filename)}
              alt={zoom.filename}
              className="max-h-[85vh] max-w-[90vw] rounded border border-panel-border object-contain"
            />
            <button
              onClick={() => setZoom(null)}
              title={t('modal.close')}
              aria-label={t('modal.close')}
              className="absolute -right-3 -top-3 flex h-7 w-7 items-center justify-center rounded-full border border-panel-border bg-panel-surface text-gray-100 shadow-lg transition hover:bg-red-600 hover:text-white"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// Icono de ojo (estilo lucide "eye"): ampliar la captura.
function EyeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}
