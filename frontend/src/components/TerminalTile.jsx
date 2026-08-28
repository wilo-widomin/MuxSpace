import React, { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../api.js'
import XtermTerminal from './XtermTerminal.jsx'
import TextComposer from './TextComposer.jsx'
import { useT } from '../i18n/index.jsx'

// Contenedor de una sesión en el grid. Incrusta la terminal de ttyd
// vía <iframe> (sección 5.4 de la especificación) y ofrece un control
// de cierre en la esquina superior derecha.
//
// La cabecera funciona como "asa" de arrastre (drag handle) para
// reordenar las ventanas. Durante un arrastre se superpone una capa
// transparente sobre el iframe: de lo contrario, el iframe captura los
// eventos del ratón y no se dispararían los `dragover`/`drop`.
//
// La cabecera tiene tres zonas, y cada una significa una cosa:
//
//   - IZQUIERDA, la identidad: el punto de estado y el nombre de la sesión,
//     y nada más. Los iconos que antes iban aquí le comían el ancho al
//     nombre en cuanto había cuatro terminales en pantalla.
//   - CENTRO, los enlaces del proyecto (si la sesión salió de uno): badges
//     con el título que el usuario le puso a cada URL. Si no caben, la zona
//     desliza en horizontal; nunca empuja al nombre ni a las acciones.
//   - DERECHA, las acciones, en dos grupos separados por una línea fina:
//     las que actúan DENTRO de la terminal (ejecutar, buscar, redactar) y
//     las que actúan SOBRE la ventana (minimizar, maximizar, matar, cerrar).
//     Antes estaban repartidas a los dos lados por ese mismo criterio, pero
//     sin nada que lo hiciera visible: parecía un grupo partido por el
//     título.
//
//   - ▶ abre la biblioteca de comandos (un desplegable con su filtro) para
//     lanzar uno en esta sesión. Antes esto era un input a lo ancho de todo
//     el tile, una línea permanente para algo que se usa de tarde en tarde.
//   - El icono de terminal abre OTRA sesión en el mismo directorio que
//     esta: el caso de "necesito una shell aquí al lado" sin tener que
//     mirar en qué carpeta estaba ni teclear un nombre. Va con los que
//     actúan DENTRO de la terminal —y el primero de todos— porque lo que
//     produce es otra terminal, no un cambio en esta ventana.
//   - 🔍 abre la búsqueda de la terminal, lo mismo que Ctrl+F. Existe porque
//     en una tableta no hay Ctrl.
export default function TerminalTile({
  session,
  isActive,
  onFocus,
  onClose,
  onKill,
  dragging,
  isDragSource,
  isOver,
  onDragStart,
  onDragEnter,
  onDragEnd,
  onDrop,
  commands = [],
  links = [],
  isFocused,
  onToggleFocus,
  onMinimize,
  onSpawn = () => {},
  onRename = async () => {},
  focusToken = 0,
}) {
  const { t, tError } = useT()
  const [search, setSearch] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [inputError, setInputError] = useState(null)
  // Cada incremento le pide a la terminal que abra su búsqueda. Es un
  // contador y no un booleano por lo mismo que `focusToken`: el hijo se lo
  // gestiona por dentro y el padre solo dispara, así no hay que sincronizar
  // dos estados de "abierto" que pueden discrepar.
  const [searchToken, setSearchToken] = useState(0)
  const [composing, setComposing] = useState(false)
  // Igual que `searchToken`: el contador es lo que dispara el pegado en la
  // terminal, y el texto viaja al lado. Con un booleano habría que apagarlo
  // después para poder volver a pegar lo mismo.
  const [paste, setPaste] = useState({ token: 0, text: '' })
  // Renombrar la sesión desde la propia cabecera. El nombre que trae una
  // sesión abierta desde un proyecto es el del proyecto con un número
  // detrás, y con tres ventanas de lo mismo en pantalla ese número no
  // dice cuál es cuál: aquí se le pone el nombre que toque sin ir a la
  // barra lateral a buscar la sesión entre todas las demás.
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState(null)
  const inputRef = useRef(null)
  const renameRef = useRef(null)

  // La lista se ofrece ORDENADA alfabéticamente: es un catálogo que se mira,
  // no un historial, y el orden en que se creó cada comando no le dice nada a
  // quien busca uno.
  const filteredCommands = useMemo(() => {
    const aguja = search.trim().toLowerCase()
    return commands
      .filter(
        (c) =>
          !aguja ||
          c.label.toLowerCase().includes(aguja) ||
          c.command.toLowerCase().includes(aguja),
      )
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [search, commands])

  // Al abrir el desplegable, el foco va al filtro: quien lo abre casi siempre
  // sabe lo que busca y quiere escribir, no apuntar con el ratón.
  useEffect(() => {
    if (showDropdown) inputRef.current?.focus()
  }, [showDropdown])

  // Escape cierra el desplegable de comandos, esté donde esté el foco. El
  // `keydown` del filtro no basta: en cuanto se pincha la lista, la terminal
  // o cualquier otra cosa, el foco se va del input y Escape dejaba de cerrar
  // nada; el único camino de vuelta era volver a pulsar el mismo botón.
  //
  // Va en fase de captura y sobre `window` porque xterm.js se come las
  // teclas que llegan a la terminal: si el foco está ahí, un listener en
  // burbuja no vería este Escape.
  useEffect(() => {
    if (!showDropdown) return
    const alPulsar = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      setShowDropdown(false)
      setSearch('')
      setInputError(null)
    }
    window.addEventListener('keydown', alPulsar, true)
    return () => window.removeEventListener('keydown', alPulsar, true)
  }, [showDropdown])

  // Al entrar en edición el texto queda seleccionado: lo normal es
  // sustituir el nombre entero, no añadirle algo al final.
  useEffect(() => {
    if (renaming) renameRef.current?.select()
  }, [renaming])

  const startRename = () => {
    setRenameValue(session.name)
    setRenameError(null)
    setRenaming(true)
  }

  const cancelRename = () => {
    setRenaming(false)
    setRenameError(null)
  }

  const submitRename = async (e) => {
    e.preventDefault()
    const nuevo = renameValue.trim()
    if (!nuevo || nuevo === session.name) {
      cancelRename()
      return
    }
    try {
      await onRename(session.name, nuevo)
      cancelRename()
    } catch (err) {
      setRenameError(tError(err))
    }
  }

  const handleKill = () => {
    // Texto completo en una sola clave (saltos de línea incluidos): partirlo
    // en trozos concatenados obligaría a traducir frases sueltas sin contexto.
    const ok = window.confirm(t('tile.confirm_kill', { name: session.name }))
    if (ok) onKill(session.name)
  }

  const handleSendCommand = async (command) => {
    try {
      await api.sendCommand(session.name, command)
      setSearch('')
      setShowDropdown(false)
      setInputError(null)
    } catch (err) {
      setInputError(tError(err))
    }
  }

  const handleKeyDown = async (e) => {
    if (e.key === 'Enter') {
      // Solo lanza comandos de la biblioteca. Antes, un texto que no
      // coincidiera con ninguno se enviaba tal cual al terminal, que es un
      // "ejecuta lo que sea" escondido en un buscador: para eso ya está la
      // propia terminal, que además muestra lo que estás escribiendo.
      if (filteredCommands.length > 0) {
        await handleSendCommand(filteredCommands[0].command)
      }
    }
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDragEnter={onDragEnter}
      onDrop={(e) => {
        e.preventDefault()
        onDrop()
      }}
      onClick={() => onFocus()}
      className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border bg-black shadow-lg transition ${
        isOver || isActive
          ? 'border-panel-accent ring-2 ring-panel-accent'
          : 'border-panel-border'
      } ${isDragSource ? 'opacity-50' : ''}`}
    >
      <div
        draggable={!renaming}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onMouseDown={() => onFocus()}
        className="flex cursor-move items-center justify-between border-b border-panel-border bg-panel-surface px-3 py-1.5 select-none"
        title={t('tile.drag_hint')}
      >
        <span className="flex min-w-0 items-center gap-2 truncate text-sm font-medium text-gray-100">
          <span className="h-2 w-2 shrink-0 rounded-full bg-green-400" />
          {renaming ? (
            <form onSubmit={submitRename} className="min-w-0 flex-1">
              <input
                ref={renameRef}
                type="text"
                value={renameValue}
                aria-label={t('tile.rename')}
                onChange={(e) => setRenameValue(e.target.value)}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') cancelRename()
                }}
                onBlur={cancelRename}
                title={renameError || undefined}
                className={`w-full rounded border bg-panel-bg px-1 py-0.5 text-sm text-gray-100 outline-none ${
                  renameError ? 'border-red-500' : 'border-panel-accent'
                }`}
              />
            </form>
          ) : (
            <span
              onDoubleClick={startRename}
              title={t('tile.rename_hint')}
              className="cursor-text truncate"
            >
              {session.name}
            </span>
          )}
        </span>

        {/* Enlaces del proyecto. `overflow-x-auto` sin barra visible: en un
            tile estrecho se deslizan con el dedo o con la rueda, que es
            mejor que recortarlos sin avisar. Y `draggable={false}` en cada
            uno porque un <a> se arrastra solo, y aquí arrastrar significa
            reordenar la ventana. */}
        {links.length > 0 && (
          <span className="mx-2 flex min-w-0 flex-1 justify-center overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <span className="flex shrink-0 items-center gap-1">
              {links.map((link) => (
                <a
                  key={link.url}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  draggable={false}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={(e) => e.stopPropagation()}
                  title={link.url}
                  className="shrink-0 cursor-pointer rounded-full border border-panel-border px-2 py-0.5 text-[11px] leading-none text-panel-muted transition hover:border-panel-accent hover:text-panel-accent"
                >
                  {link.title}
                </a>
              ))}
            </span>
          </span>
        )}

        {/* `relative` para que el desplegable de comandos cuelgue de su
            botón. Y el `onMouseDown` con stopPropagation en los del grupo
            izquierdo: la cabecera es el asa de arrastre, y sin esto pulsar
            un icono empieza un arrastre. */}
        <span className="relative flex shrink-0 items-center gap-0.5">
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => onSpawn(session.name)}
            title={t('tile.new_terminal')}
            aria-label={t('tile.new_terminal')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-green-400"
          >
            <TerminalIcon />
          </button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => setShowDropdown((abierto) => !abierto)}
            title={t('tile.run_command')}
            aria-label={t('tile.run_command')}
            aria-expanded={showDropdown}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-green-400"
          >
            <PlayIcon />
          </button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => setSearchToken((n) => n + 1)}
            title={t('tile.search_terminal')}
            aria-label={t('tile.search_terminal')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <SearchIcon />
          </button>
          <button
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => setComposing((abierto) => !abierto)}
            title={t('tile.compose')}
            aria-label={t('tile.compose')}
            aria-pressed={composing}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <PencilIcon />
          </button>
          <span className="mx-1 h-4 w-px shrink-0 bg-panel-border" />
          <button
            onClick={onMinimize}
            title={t('tile.minimize')}
            aria-label={t('tile.minimize')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <MinimizeIcon />
          </button>
          <button
            onClick={onToggleFocus}
            title={isFocused ? t('tile.restore') : t('tile.maximize')}
            aria-label={isFocused ? t('tile.restore') : t('tile.maximize')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <MaximizeIcon />
          </button>
          <button
            onClick={handleKill}
            title={t('tile.kill')}
            className="rounded p-1 text-panel-muted transition hover:bg-red-500/20 hover:text-red-400"
          >
            <DoorIcon />
          </button>
          <button
            onClick={() => onClose(session.name)}
            title={t('tile.close')}
            className="rounded p-1 text-panel-muted transition hover:bg-red-500/20 hover:text-red-400"
          >
            <CloseIcon />
          </button>
        </span>
      </div>

      <div className="relative min-h-0 flex-1">
        {/* Terminal xterm.js propia sobre WebSocket->PTY (sustituye al iframe
            de ttyd) para poder copiar al portapapeles con navigator.clipboard. */}
        <XtermTerminal
          name={session.name}
          onFocus={() => onFocus()}
          focusToken={focusToken}
          searchToken={searchToken}
          pasteRequest={paste}
        />
        {composing && (
          <TextComposer
            name={session.name}
            onClose={() => setComposing(false)}
            onPaste={(texto) => setPaste((p) => ({ token: p.token + 1, text: texto }))}
          />
        )}
        {/* La lista de comandos se pinta AQUÍ, sobre la terminal, y no
            colgando del botón ▶: el tile lleva `overflow-hidden` por las
            esquinas redondeadas, así que ahí arriba quedaba recortada y solo
            se veía el filtro. */}
        {showDropdown && (
          <div className="absolute top-1 left-2 z-30 w-64 rounded border border-panel-border bg-panel-surface shadow-lg">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('tile.command_filter_placeholder')}
              className="w-full border-b border-panel-border bg-transparent px-2 py-1 text-xs text-gray-100 placeholder:text-panel-muted outline-none"
            />
            <ul className="max-h-64 overflow-y-auto">
              {filteredCommands.map((c) => (
                <li
                  key={c.id}
                  onClick={() => handleSendCommand(c.command)}
                  className="cursor-pointer px-2 py-1 text-xs text-panel-muted hover:bg-panel-bg hover:text-gray-100"
                  title={c.command}
                >
                  {c.label}
                </li>
              ))}
              {filteredCommands.length === 0 && (
                <li className="px-2 py-1 text-xs text-panel-muted">
                  {t('tile.no_commands')}
                </li>
              )}
            </ul>
            {inputError && (
              <p className="px-2 py-1 text-xs text-red-400">{inputError}</p>
            )}
          </div>
        )}
        {/* Capa que intercepta los eventos de arrastre sobre la terminal. */}
        {dragging && <div className="absolute inset-0 z-10" />}
      </div>
    </div>
  )
}

// Triángulo de "ejecutar" (estilo lucide "play"), el mismo de la biblioteca
// de comandos del Sidebar: la acción es la misma, el icono también.
function PlayIcon() {
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
      <polygon points="6 3 20 12 6 21 6 3" />
    </svg>
  )
}

// Lápiz sobre hoja (estilo lucide "square-pen"): redactar un texto largo sin
// que Enter lo envíe.
function PencilIcon() {
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
      <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.375 2.625a1.768 1.768 0 0 1 2.5 2.5L12 14l-4 1 1-4Z" />
    </svg>
  )
}

// Ventana de terminal con un prompt (estilo lucide "square-terminal"): abre
// OTRA terminal en el mismo directorio que esta. El icono dice "terminal", y
// el sitio donde está —el grupo que actúa sobre la ventana— dice "otra".
function TerminalIcon() {
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
      <path d="m7 11 2-2-2-2" />
      <path d="M11 13h4" />
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
    </svg>
  )
}

// Lupa (estilo lucide "search"): abre la búsqueda de la terminal sin teclado.
function SearchIcon() {
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
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
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

// Flechas hacia fuera (estilo lucide "maximize"): maximizar esta terminal.
// Una raya abajo: la terminal sale de la rejilla y queda como pestaña.
function MinimizeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 18h14" />
    </svg>
  )
}

function MaximizeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
      <path d="M3 16v3a2 2 0 0 0 2 2h3" />
      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
    </svg>
  )
}

// Icono de puerta abierta (estilo lucide "door-open"): terminar sesión.
function DoorIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M13 4h3a2 2 0 0 1 2 2v14" />
      <path d="M2 20h3" />
      <path d="M13 20h9" />
      <path d="M10 12v.01" />
      <path d="M13 4.562v16.157a1 1 0 0 1-1.242.97L5 20V5.562a2 2 0 0 1 1.515-1.94l4-1A2 2 0 0 1 13 4.561Z" />
    </svg>
  )
}
