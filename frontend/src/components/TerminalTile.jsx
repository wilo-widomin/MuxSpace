import React, { useState, useEffect } from 'react'
import { api } from '../api.js'
import XtermTerminal from './XtermTerminal.jsx'
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
// Incluye un input de búsqueda para comandos de la biblioteca.
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
  isFocused,
  onToggleFocus,
  focusToken = 0,
}) {
  const { t, tError } = useT()
  const [search, setSearch] = useState('')
  const [filteredCommands, setFilteredCommands] = useState([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [inputError, setInputError] = useState(null)

  // Filtrar comandos al escribir
  useEffect(() => {
    if (search.length > 0) {
      const matches = commands.filter((c) =>
        c.label.toLowerCase().includes(search.toLowerCase()) ||
        c.command.toLowerCase().includes(search.toLowerCase())
      )
      setFilteredCommands(matches)
      setShowDropdown(true)
    } else {
      setFilteredCommands([])
      setShowDropdown(false)
    }
  }, [search, commands])

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
      if (filteredCommands.length > 0) {
        // Usar el primer match
        await handleSendCommand(filteredCommands[0].command)
      } else {
        // Enviar texto literal
        await handleSendCommand(search)
      }
    } else if (e.key === 'Escape') {
      setSearch('')
      setShowDropdown(false)
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
        draggable
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onMouseDown={() => onFocus()}
        className="flex cursor-move items-center justify-between border-b border-panel-border bg-panel-surface px-3 py-1.5 select-none"
        title={t('tile.drag_hint')}
      >
        <span className="flex items-center gap-2 truncate text-sm font-medium text-gray-100">
          <span className="h-2 w-2 rounded-full bg-green-400" />
          <span className="truncate">{session.name}</span>
        </span>
        <span className="flex items-center gap-0.5">
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

      {/* Input de búsqueda de comandos */}
      <div className="relative border-b border-panel-border bg-panel-surface px-3 py-1">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            onFocus()
            if (search.length > 0) setShowDropdown(true)
          }}
          onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
          placeholder={t('tile.search_placeholder')}
          className="w-full bg-transparent text-sm text-gray-100 placeholder:text-panel-muted outline-none"
        />
        {inputError && (
          <p className="mt-1 text-xs text-red-400">{inputError}</p>
        )}
        {showDropdown && filteredCommands.length > 0 && (
          <div className="absolute top-full left-0 z-20 mt-1 w-full rounded border border-panel-border bg-panel-surface shadow-lg">
            <ul className="max-h-48 overflow-y-auto">
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
            </ul>
          </div>
        )}
      </div>

      <div className="relative min-h-0 flex-1">
        {/* Terminal xterm.js propia sobre WebSocket->PTY (sustituye al iframe
            de ttyd) para poder copiar al portapapeles con navigator.clipboard. */}
        <XtermTerminal
          name={session.name}
          onFocus={() => onFocus()}
          focusToken={focusToken}
        />
        {/* Capa que intercepta los eventos de arrastre sobre la terminal. */}
        {dragging && <div className="absolute inset-0 z-10" />}
      </div>
    </div>
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