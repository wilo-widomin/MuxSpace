import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api.js'
import { useT } from '../i18n/index.jsx'

// Buscador de la conversación de Claude, sobre la terminal.
//
// POR QUÉ EXISTE: un panel donde corre Claude Code ocupa la pantalla
// alternativa del terminal. tmux no guarda ni una línea de eso (historial 0),
// así que la búsqueda del copy-mode —la que usa el panel en una shell— no
// tiene ahí nada que mirar: lo que se fue por arriba solo se recupera
// haciendo scroll dentro de Claude, a ojo.
//
// La conversación sí está en disco (`~/.claude/projects/**.jsonl`), así que
// aquí se pinta entera en un modal y se busca sobre texto del navegador. Eso
// da lo que no podía dar tmux en ese panel: saltar a la coincidencia y
// resaltarla.
//
// LÍMITE HONESTO: esto no mueve la vista de Claude ni habla con él. Es una
// copia de la conversación para leer y buscar; el panel de detrás sigue donde
// estaba.

const RESALTADO = 'bg-yellow-500/30 text-gray-100'
const RESALTADO_ACTUAL = 'bg-yellow-400 text-black'

// Los cuatro tipos de bloque que trae un transcript, en el orden en que se
// ofrecen como filtro. El orden importa poco salvo por costumbre: primero lo
// que casi siempre se quiere ver.
const TIPOS = ['text', 'tool_use', 'tool_result', 'thinking']

const CLAVE_FILTROS = 'muxspace.transcript.filtros'

// Qué se muestra al abrir. Se guarda en localStorage porque es una
// preferencia de lectura, no algo que apetezca volver a elegir cada vez.
function filtrosIniciales() {
  try {
    const guardado = JSON.parse(localStorage.getItem(CLAVE_FILTROS))
    if (Array.isArray(guardado) && guardado.length) {
      return TIPOS.filter((tipo) => guardado.includes(tipo))
    }
  } catch {
    /* localStorage lleno o con basura: se usan los de fábrica */
  }
  return TIPOS
}

// Trocea un texto en fragmentos, marcando las coincidencias. El índice global
// que recibe cada una es lo que permite navegar «3 de 17» por todo el modal,
// y no por bloque.
export function trocear(texto, aguja, indiceInicial) {
  if (!aguja) return { partes: [{ texto, coincidencia: false }], total: 0 }
  const partes = []
  const bajo = texto.toLowerCase()
  const objetivo = aguja.toLowerCase()
  let desde = 0
  let n = 0
  for (;;) {
    const encontrado = bajo.indexOf(objetivo, desde)
    if (encontrado === -1) break
    if (encontrado > desde) {
      partes.push({ texto: texto.slice(desde, encontrado), coincidencia: false })
    }
    partes.push({
      texto: texto.slice(encontrado, encontrado + aguja.length),
      coincidencia: true,
      indice: indiceInicial + n,
    })
    n += 1
    desde = encontrado + aguja.length
  }
  if (desde < texto.length) {
    partes.push({ texto: texto.slice(desde), coincidencia: false })
  }
  return { partes, total: n }
}

function Bloque({ bloque, aguja, indiceInicial, actual, refActual }) {
  const { partes } = useMemo(
    () => trocear(bloque.text, aguja, indiceInicial),
    [bloque.text, aguja, indiceInicial]
  )
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-200">
      {partes.map((parte, i) =>
        parte.coincidencia ? (
          <mark
            key={i}
            ref={parte.indice === actual ? refActual : null}
            className={parte.indice === actual ? RESALTADO_ACTUAL : RESALTADO}
          >
            {parte.texto}
          </mark>
        ) : (
          <span key={i}>{parte.texto}</span>
        )
      )}
    </pre>
  )
}

export default function TranscriptSearch({ name, onClose }) {
  const { t, tError } = useT()
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const [aguja, setAguja] = useState('')
  const [actual, setActual] = useState(0)
  const [filtros, setFiltros] = useState(filtrosIniciales)
  const contenedorRef = useRef(null)
  const finRef = useRef(null)
  const marcaActualRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    let vivo = true
    api
      .getTranscript(name)
      .then((d) => vivo && setDatos(d))
      .catch((e) => vivo && setError(e instanceof ApiError ? e : new ApiError(0)))
    return () => {
      vivo = false
    }
  }, [name])

  // Al abrir se entra por el final, que es donde estabas mirando.
  useEffect(() => {
    if (datos?.available) finRef.current?.scrollIntoView()
    inputRef.current?.focus()
  }, [datos])

  // Memoizado y no calculado al vuelo: si la lista fuera nueva en cada
  // render, el índice de coincidencias (que recorre toda la conversación) se
  // recalcularía con cada pulsación de tecla.
  //
  // El filtro se aplica AQUÍ, antes de numerar las coincidencias: así lo que
  // se cuenta es lo que se ve. Contar en lo oculto haría que «3 de 17» te
  // llevara a sitios inexistentes.
  const mensajes = useMemo(() => {
    const todos = datos?.available ? datos.messages : []
    return todos
      .map((m) => ({ ...m, blocks: m.blocks.filter((b) => filtros.includes(b.kind)) }))
      .filter((m) => m.blocks.length > 0)
  }, [datos, filtros])

  // Cuántos bloques hay de cada tipo, para poder decirlo en su pastilla. Se
  // cuenta sobre el transcript ENTERO, no sobre lo filtrado: es el número que
  // se recupera al volver a activarlo.
  const totales = useMemo(() => {
    const cuenta = Object.fromEntries(TIPOS.map((tipo) => [tipo, 0]))
    for (const m of datos?.available ? datos.messages : []) {
      for (const b of m.blocks) {
        if (b.kind in cuenta) cuenta[b.kind] += 1
      }
    }
    return cuenta
  }, [datos])

  const alternarFiltro = useCallback((tipo) => {
    setFiltros((actuales) => {
      const siguiente = actuales.includes(tipo)
        ? actuales.filter((x) => x !== tipo)
        : TIPOS.filter((x) => actuales.includes(x) || x === tipo)
      try {
        localStorage.setItem(CLAVE_FILTROS, JSON.stringify(siguiente))
      } catch {
        /* no poder recordarlo no impide usarlo ahora */
      }
      return siguiente
    })
  }, [])

  // Numeración global de coincidencias: cada bloque necesita saber por qué
  // índice empieza para que la navegación recorra el modal entero en orden.
  const { indices, total } = useMemo(() => {
    const acumulado = []
    let n = 0
    for (const mensaje of mensajes) {
      const porBloque = []
      for (const bloque of mensaje.blocks) {
        porBloque.push(n)
        n += trocear(bloque.text, aguja, 0).total
      }
      acumulado.push(porBloque)
    }
    return { indices: acumulado, total: n }
  }, [mensajes, aguja])

  // Cambiar el texto o los filtros renumera las coincidencias: seguir en la
  // número 12 de una lista que ya no existe llevaría a cualquier sitio.
  useEffect(() => {
    setActual(0)
  }, [aguja, filtros])

  // Traer a la vista la coincidencia activa: es lo que convierte esto en un
  // buscador y no en una lista que hay que repasar con los ojos.
  useEffect(() => {
    if (total > 0) marcaActualRef.current?.scrollIntoView({ block: 'center' })
  }, [actual, total, aguja])

  const mover = useCallback(
    (paso) => {
      if (!total) return
      setActual((n) => (n + paso + total) % total)
    },
    [total]
  )

  const onTecla = useCallback(
    (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        mover(e.shiftKey ? -1 : 1)
      } else if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    },
    [mover, onClose]
  )

  return (
    <div className="absolute inset-0 z-40 flex flex-col bg-panel-bg">
      <div className="flex items-center gap-2 border-b border-panel-border bg-panel-surface px-3 py-2">
        <span className="truncate text-xs text-panel-muted">
          {t('transcript.title', { name })}
        </span>
        <input
          ref={inputRef}
          type="text"
          value={aguja}
          onChange={(e) => setAguja(e.target.value)}
          onKeyDown={onTecla}
          placeholder={t('transcript.search_placeholder')}
          className="ml-auto w-56 rounded border border-panel-accent bg-panel-bg px-2 py-1 text-xs text-gray-100 placeholder:text-panel-muted outline-none ring-1 ring-panel-accent/40"
        />
        {aguja && (
          <span
            className={`whitespace-nowrap text-xs ${
              total ? 'text-panel-muted' : 'text-red-400'
            }`}
          >
            {total
              ? t('transcript.position', { current: actual + 1, total })
              : t('term.search_none')}
          </span>
        )}
        <button
          type="button"
          onClick={() => mover(-1)}
          title={t('term.search_prev')}
          className="px-1 text-xs text-panel-muted hover:text-gray-100"
        >
          ↑
        </button>
        <button
          type="button"
          onClick={() => mover(1)}
          title={t('term.search_next')}
          className="px-1 text-xs text-panel-muted hover:text-gray-100"
        >
          ↓
        </button>
        <button
          type="button"
          onClick={onClose}
          title={t('term.search_close')}
          className="px-1 text-sm text-panel-muted hover:text-gray-100"
        >
          ×
        </button>
      </div>

      {/* Alineadas a la derecha para que caigan bajo el buscador: son sus
          controles, y a la izquierda parecían de otra cosa. */}
      <div className="flex flex-wrap items-center justify-end gap-1 border-b border-panel-border bg-panel-surface px-3 py-1">
        <span className="mr-1 text-[10px] uppercase tracking-wide text-panel-muted">
          {t('transcript.filters')}
        </span>
        {TIPOS.map((tipo) => {
          const activo = filtros.includes(tipo)
          return (
            <button
              key={tipo}
              type="button"
              onClick={() => alternarFiltro(tipo)}
              aria-pressed={activo}
              className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                activo
                  ? 'border-panel-accent bg-panel-accent/20 text-gray-100'
                  : 'border-panel-border text-panel-muted hover:text-gray-100'
              }`}
            >
              {t(`transcript.block_${tipo}`)}
              <span className="ml-1 opacity-60">{totales[tipo]}</span>
            </button>
          )
        })}
      </div>

      <div ref={contenedorRef} className="flex-1 overflow-y-auto px-3 py-2">
        {error && <p className="text-xs text-red-400">{tError(error)}</p>}
        {!error && datos === null && (
          <p className="text-xs text-panel-muted">{t('transcript.loading')}</p>
        )}
        {datos && !datos.available && (
          <p className="text-xs text-panel-muted">{t('transcript.unavailable')}</p>
        )}
        {mensajes.map((mensaje, i) => (
          <div key={i} className="mb-3 border-l-2 border-panel-border pl-2">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-panel-muted">
              {t(`transcript.role_${mensaje.role}`)} · {mensaje.timestamp.slice(11, 19)}
            </div>
            {mensaje.blocks.map((bloque, j) => (
              <div key={j} className={bloque.kind === 'text' ? '' : 'opacity-70'}>
                {bloque.kind !== 'text' && (
                  <div className="text-[10px] text-panel-muted">
                    {bloque.kind === 'tool_use'
                      ? `⚙ ${bloque.name}`
                      : t(`transcript.block_${bloque.kind}`)}
                  </div>
                )}
                <Bloque
                  bloque={bloque}
                  aguja={aguja}
                  indiceInicial={indices[i]?.[j] ?? 0}
                  actual={actual}
                  refActual={marcaActualRef}
                />
              </div>
            ))}
          </div>
        ))}
        <div ref={finRef} />
      </div>
    </div>
  )
}
