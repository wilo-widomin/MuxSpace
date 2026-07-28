// El `Modal` del sidebar: la primitiva de la que cuelgan los cinco diálogos
// (nueva sesión, nuevo/editar comando, nuevo/editar proyecto) y el
// `DirBrowserModal` que extrae US-014.
//
// `CloseIcon` y `FolderIcon` viven aquí y se re-exportan. No es su sitio
// natural —los usan varios puntos de `Sidebar.jsx` y de `DirBrowserModal`—
// pero las alternativas eran peores:
// duplicarlo (prohibido por la historia), dejarlo en `Sidebar.jsx` e
// importarlo desde aquí (import circular: Sidebar -> Modal -> Sidebar), o
// crear ya `components/icons.jsx`, que US-011 dejó explícitamente fuera de
// alcance. Se juntan aquí a propósito, en UN solo sitio: el día que exista
// esa colección, moverlos es cortar y pegar dos funciones seguidas.
import { useEffect } from 'react'

import { useT } from '../../i18n/index.jsx'

// Modal centrado sobre un overlay oscuro. Cierra con Escape, clic en el
// backdrop o en el botón X de la cabecera. El body hace scroll si el
// contenido es alto. `panelClassName` controla el ancho (max-w-md por
// defecto; las que llevan listas usan max-w-lg).
export function Modal({ title, onClose, children, panelClassName = 'max-w-md' }) {
  const { t } = useT()
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onMouseDown={onClose}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className={`flex max-h-[85vh] w-full flex-col rounded-lg border border-panel-border bg-panel-surface shadow-2xl ${panelClassName}`}
      >
        <header className="flex items-center justify-between border-b border-panel-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-gray-100">{title}</h2>
          <button
            onClick={onClose}
            title={t('modal.close')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <CloseIcon />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
      </div>
    </div>
  )
}


export function CloseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}


export function FolderIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2Z" />
    </svg>
  )
}
