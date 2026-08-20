import React, { useState, useEffect, useRef, useCallback } from 'react'
import TerminalTile from './TerminalTile.jsx'
import { useT } from '../i18n/index.jsx'

// Grid Dinámico (Auto-Layout). Reparte el espacio de forma equitativa:
// recalcula filas y columnas para que todas las terminales ocupen la
// misma área proporcional (1 sesión = 100%, 4 sesiones = 2x2).
//
// Además, las líneas entre columnas y entre filas son arrastrables: el
// reparto deja de ser equitativo y pasa a guardarse como pesos `fr` por
// eje. Cada tamaño se recuerda por forma de rejilla (2x2, 3x2, ...) en
// localStorage, porque al abrir o cerrar terminales el grid cambia de
// forma y unos pesos de 3 columnas no significan nada en una de 2.
//
// La disposición tiene tres modos: 'auto' reparte en cuadrícula, 'cols'
// pone todas las terminales en fila (una al lado de otra) y 'rows' las
// apila (una encima de otra). El modo elegido se recuerda entre sesiones.
function computeGrid(count, mode) {
  if (count <= 0) return { cols: 1, rows: 1 }
  if (mode === 'cols') return { cols: count, rows: 1 }
  if (mode === 'rows') return { cols: 1, rows: count }
  const cols = Math.ceil(Math.sqrt(count))
  const rows = Math.ceil(count / cols)
  return { cols, rows }
}

// El modo vive en App (los botones están en la cabecera de la barra
// lateral), así que aquí solo se recibe como prop.
export const LAYOUTS = ['auto', 'cols', 'rows']

// Grosor del canal entre tiles: es a la vez la separación visual y la
// zona de agarre del separador.
const GUTTER = 12
// Peso mínimo de una pista para que un tile no se pueda aplastar a cero.
const MIN_FR = 0.15

const storageKey = (cols, rows) => `muxspace:grid-sizes:${cols}x${rows}`

// Pesos guardados para esta forma de rejilla, o reparto equitativo.
function loadSizes(cols, rows) {
  const equal = { colFr: Array(cols).fill(1), rowFr: Array(rows).fill(1) }
  try {
    const raw = window.localStorage.getItem(storageKey(cols, rows))
    if (!raw) return equal
    const saved = JSON.parse(raw)
    // Descartamos lo guardado si no encaja con la forma actual: es más
    // seguro volver a equitativo que renderizar un grid inconsistente.
    if (
      Array.isArray(saved.colFr) &&
      Array.isArray(saved.rowFr) &&
      saved.colFr.length === cols &&
      saved.rowFr.length === rows &&
      saved.colFr.every((n) => typeof n === 'number' && n > 0) &&
      saved.rowFr.every((n) => typeof n === 'number' && n > 0)
    ) {
      return { colFr: saved.colFr, rowFr: saved.rowFr }
    }
  } catch {
    /* localStorage no disponible o JSON corrupto: reparto equitativo */
  }
  return equal
}

// `[1, 2, 1]` -> "1fr 12px 2fr 12px 1fr": pistas de contenido separadas
// por canales fijos que hacen de gap y de zona de agarre.
const toTemplate = (fr) => fr.map((f) => `${f}fr`).join(` ${GUTTER}px `)

export default function SessionGrid({
  openSessions,
  activeName,
  onSetActive,
  onClose,
  onKill,
  onReorder,
  commands,
  layout,
  focusedName,
  onSetFocused,
  minimizedNames = new Set(),
  onToggleMinimized = () => {},
  onRestoreAllMinimized = () => {},
  focusName = null,
  focusToken = 0,
}) {
  const { t } = useT()
  // Nombre de la ventana que se arrastra y sobre cuál se está soltando.
  const [dragName, setDragName] = useState(null)
  const [overName, setOverName] = useState(null)

  // Las minimizadas siguen abiertas y montadas, pero no cuentan para el
  // reparto del espacio: la rejilla se calcula solo con las visibles. Los
  // pesos de los separadores ya se guardan por forma (2x1, 2x2...), así que
  // minimizar recuerda los tamaños de esa forma y restaurar, los de la otra.
  const visibleSessions = openSessions.filter((s) => !minimizedNames.has(s.name))
  const minimizedSessions = openSessions.filter((s) => minimizedNames.has(s.name))

  const { cols, rows } = computeGrid(visibleSessions.length, layout)
  const gridRef = useRef(null)
  const [sizes, setSizes] = useState(() => loadSizes(cols, rows))

  // Al cambiar la forma de la rejilla (abrir/cerrar una terminal) hay que
  // recuperar los pesos de ESA forma; los de la anterior ya no aplican.
  useEffect(() => {
    setSizes(loadSizes(cols, rows))
  }, [cols, rows])

  const persist = useCallback(
    (next) => {
      try {
        window.localStorage.setItem(storageKey(cols, rows), JSON.stringify(next))
      } catch {
        /* modo privado o cuota llena: el tamaño solo dura la sesión */
      }
    },
    [cols, rows],
  )

  // Arrastre de un separador. `axis` es 'col' o 'row' e `index` es el hueco
  // entre la pista `index` y la `index + 1`: el delta se reparte entre esas
  // dos y el resto del grid no se mueve.
  const startDrag = (axis, index) => (e) => {
    e.preventDefault()
    e.stopPropagation()
    const grid = gridRef.current
    if (!grid) return

    const horizontal = axis === 'col'
    const key = horizontal ? 'colFr' : 'rowFr'
    const startPos = horizontal ? e.clientX : e.clientY
    const startFr = sizes[key]
    const count = startFr.length
    const totalFr = startFr.reduce((a, b) => a + b, 0)

    // Píxeles que vale 1fr ahora mismo: el espacio libre tras descontar los
    // canales fijos, repartido entre el total de pesos.
    const rect = grid.getBoundingClientRect()
    const available = (horizontal ? rect.width : rect.height) - GUTTER * (count - 1)
    if (available <= 0) return
    const pxPerFr = available / totalFr

    const pair = startFr[index] + startFr[index + 1]

    const onMove = (ev) => {
      const delta = (horizontal ? ev.clientX : ev.clientY) - startPos
      let first = startFr[index] + delta / pxPerFr
      // Clamp: ninguna de las dos pistas baja de MIN_FR, y su suma se
      // conserva para que el resto de la rejilla no se mueva.
      first = Math.max(MIN_FR, Math.min(pair - MIN_FR, first))
      const next = [...startFr]
      next[index] = first
      next[index + 1] = pair - first
      setSizes((prev) => ({ ...prev, [key]: next }))
    }

    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      // Guardamos desde el updater para leer el último estado ya aplicado.
      setSizes((prev) => {
        persist(prev)
        return prev
      })
    }

    // Mientras se arrastra, el cursor y el bloqueo de selección son
    // globales: el puntero se sale del separador enseguida.
    document.body.style.cursor = horizontal ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  // Doble clic sobre un separador: vuelve a repartir ese eje a partes iguales.
  const resetAxis = (axis) => () => {
    const key = axis === 'col' ? 'colFr' : 'rowFr'
    setSizes((prev) => {
      const next = { ...prev, [key]: Array(prev[key].length).fill(1) }
      persist(next)
      return next
    })
  }

  if (openSessions.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-panel-muted">
        <div>
          <p className="text-lg font-medium">{t('grid.empty_title')}</p>
          <p className="mt-1 text-sm">{t('grid.empty_hint')}</p>
        </div>
      </div>
    )
  }

  const finishDrag = (targetName) => {
    if (dragName && targetName && dragName !== targetName) {
      onReorder(dragName, targetName)
    }
    setDragName(null)
    setOverName(null)
  }

  // Las pistas de contenido son las impares (1, 3, 5...) en coordenadas de
  // grid 1-based; las pares son los canales donde viven los separadores.
  const trackLine = (i) => 2 * i + 1
  const gutterLine = (i) => 2 * i + 2

  // Modo foco: una terminal ocupa todo el grid y las demás se esconden con
  // CSS. Se ocultan, no se desmontan: al desmontarlas se cerraría su
  // WebSocket y perderían el scrollback de xterm.
  const isFocus = visibleSessions.some((s) => s.name === focusedName)

  // La barra de arriba lista lo que NO está repartiéndose el espacio abajo:
  // en modo foco, todas las terminales (para saltar entre ellas); fuera de
  // él, solo las minimizadas (para devolverlas a la rejilla).
  const tabs = isFocus ? visibleSessions : minimizedSessions
  const showTabs = isFocus || minimizedSessions.length > 0

  return (
    <div className="flex h-full w-full flex-col">
      {showTabs && (
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-panel-border bg-panel-surface px-3 py-1">
          {tabs.map((session) => {
            const isMinimized = minimizedNames.has(session.name)
            return (
              <button
                key={session.name}
                onClick={() =>
                  isMinimized
                    ? onToggleMinimized(session.name)
                    : onSetFocused(session.name)
                }
                title={isMinimized ? t('grid.restore_one') : session.name}
                aria-pressed={session.name === focusedName}
                className={`flex shrink-0 items-center gap-1.5 rounded px-2 py-1 text-xs transition ${
                  session.name === focusedName
                    ? 'bg-panel-bg text-gray-100'
                    : 'text-panel-muted hover:bg-panel-bg hover:text-gray-100'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    isMinimized ? 'bg-panel-muted' : 'bg-green-400'
                  }`}
                />
                <span className="max-w-[14ch] truncate">{session.name}</span>
              </button>
            )
          })}
          <span className="ml-auto flex shrink-0 items-center gap-0.5">
            {minimizedSessions.length > 1 && (
              <button
                onClick={onRestoreAllMinimized}
                title={t('grid.restore_all')}
                aria-label={t('grid.restore_all')}
                className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
              >
                <RestoreIcon />
              </button>
            )}
            {isFocus && (
              <button
                onClick={() => onSetFocused(null)}
                title={t('grid.restore')}
                aria-label={t('grid.restore')}
                className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
              >
                <RestoreIcon />
              </button>
            )}
          </span>
        </div>
      )}
      <div
        ref={gridRef}
        className="relative grid min-h-0 w-full flex-1 p-3"
        style={
          isFocus
            ? { gridTemplateColumns: '1fr', gridTemplateRows: '1fr' }
            : {
                gridTemplateColumns: toTemplate(sizes.colFr),
                gridTemplateRows: toTemplate(sizes.rowFr),
              }
        }
      >
        {/* Todas las terminales se renderizan siempre, también las que están
            escondidas: al desmontarlas se cerraría su WebSocket y perderían
            el scrollback de xterm. Su sitio en la rejilla se calcula con el
            índice entre las VISIBLES, no entre todas. */}
        {visibleSessions.length === 0 && (
          <p className="absolute inset-0 flex items-center justify-center text-center text-sm text-panel-muted">
            {t('grid.all_minimized')}
          </p>
        )}
        {openSessions.map((session) => {
          const visibleIndex = visibleSessions.indexOf(session)
          const col = visibleIndex % cols
          const row = Math.floor(visibleIndex / cols)
          const hidden =
            visibleIndex === -1 || (isFocus && session.name !== focusedName)
          return (
            <div
              key={session.name}
              className="flex min-h-0 min-w-0"
              style={
                hidden
                  ? { display: 'none' }
                  : isFocus
                    ? { gridColumn: 1, gridRow: 1 }
                    : { gridColumn: trackLine(col), gridRow: trackLine(row) }
              }
            >
              <TerminalTile
                session={session}
                isActive={activeName === session.name}
                onFocus={() => onSetActive(session.name)}
                onClose={onClose}
                onKill={onKill}
                commands={commands}
                dragging={dragName !== null}
                isDragSource={dragName === session.name}
                isOver={overName === session.name && dragName !== session.name}
                onDragStart={() => setDragName(session.name)}
                onDragEnter={() => setOverName(session.name)}
                onDragEnd={() => {
                  setDragName(null)
                  setOverName(null)
                }}
                onDrop={() => finishDrag(session.name)}
                onMinimize={() => onToggleMinimized(session.name)}
                isFocused={session.name === focusedName}
                onToggleFocus={() =>
                  onSetFocused(session.name === focusedName ? null : session.name)
                }
                focusToken={focusName === session.name ? focusToken : 0}
              />
            </div>
          )
        })}

        {/* Separadores verticales: uno por hueco entre columnas. */}
        {!isFocus &&
          Array.from({ length: cols - 1 }, (_, i) => (
            <div
              key={`col-${i}`}
              onPointerDown={startDrag('col', i)}
              onDoubleClick={resetAxis('col')}
              title={t('grid.resize_hint')}
              className="group z-20 flex cursor-col-resize items-center justify-center"
              style={{ gridColumn: gutterLine(i), gridRow: '1 / -1' }}
            >
              <div className="h-full w-[3px] rounded-full bg-transparent transition group-hover:bg-panel-accent/60" />
            </div>
          ))}

        {/* Separadores horizontales: uno por hueco entre filas. */}
        {!isFocus &&
          Array.from({ length: rows - 1 }, (_, i) => (
            <div
              key={`row-${i}`}
              onPointerDown={startDrag('row', i)}
              onDoubleClick={resetAxis('row')}
              title={t('grid.resize_hint')}
              className="group z-10 flex cursor-row-resize items-center justify-center"
              style={{ gridRow: gutterLine(i), gridColumn: '1 / -1' }}
            >
              <div className="h-[3px] w-full rounded-full bg-transparent transition group-hover:bg-panel-accent/60" />
            </div>
          ))}
      </div>
    </div>
  )
}

// Flechas hacia dentro (estilo lucide "minimize"): salir del modo foco.
function RestoreIcon() {
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
      <path d="M8 3v3a2 2 0 0 1-2 2H3" />
      <path d="M21 8h-3a2 2 0 0 1-2-2V3" />
      <path d="M3 16h3a2 2 0 0 1 2 2v3" />
      <path d="M16 21v-3a2 2 0 0 1 2-2h3" />
    </svg>
  )
}

// Miniatura de la disposición: cuadrícula, columnas o filas.
export function LayoutIcon({ mode }) {
  const rects =
    mode === 'cols'
      ? [
          [3, 3, 7, 18],
          [14, 3, 7, 18],
        ]
      : mode === 'rows'
        ? [
            [3, 3, 18, 7],
            [3, 14, 18, 7],
          ]
        : [
            [3, 3, 7, 7],
            [14, 3, 7, 7],
            [3, 14, 7, 7],
            [14, 14, 7, 7],
          ]
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      {rects.map(([x, y, w, h]) => (
        <rect
          key={`${x}-${y}`}
          x={x}
          y={y}
          width={w}
          height={h}
          rx="1.5"
          fill="currentColor"
        />
      ))}
    </svg>
  )
}
