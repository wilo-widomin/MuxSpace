import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api.js'
import { useT } from '../i18n/index.jsx'
import {
  DEFAULT_FILTERS,
  KINDS,
  buildSearchBody,
  describeError,
  formatIsoDate,
  projectName,
  roleKey,
  toggleKind,
} from '../lib/claudeSessions.js'
import { formatTime } from '../worklog.js'
import { ClaudeSnippet } from './ClaudeSnippet.jsx'

// Conversaciones pasadas de Claude Code: búsqueda global, lista de un proyecto,
// visor y «retomar». Es una pantalla encima del panel (no una ruta nueva)
// porque «Retomar en el grid» tiene que abrir la terminal en ESTA página, la
// que tiene el grid.
//
// Lo que se lee aquí se consulta al momento y se tira: nada se guarda en el
// navegador (ni `localStorage`) ni se cachea. Los controles son grandes y
// funcionan sin teclado completo ni ratón (tablet con Unexpected Keyboard).

const BOTON =
  'inline-flex min-h-[2.75rem] items-center justify-center rounded border border-panel-border px-3 text-sm text-gray-100 transition hover:bg-panel-bg disabled:opacity-50'
const BOTON_PRIMARIO =
  'inline-flex min-h-[2.75rem] items-center justify-center rounded bg-panel-accent px-3 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50'
const CAMPO =
  'min-h-[2.75rem] w-full rounded border border-panel-border bg-panel-bg px-3 text-sm text-gray-100 focus:border-panel-accent focus:outline-none'

// Un error de la petición. El 503 enseña el mensaje y el comando del API
// literales; no hay ningún botón que intente encender las sesiones.
function ErrorBox({ error }) {
  const { t, tError } = useT()
  if (!error) return null
  const vista = describeError(error)
  if (vista.kind === 'disabled') {
    return (
      <div
        role="alert"
        className="rounded border border-yellow-600/60 bg-yellow-900/20 p-3 text-sm"
      >
        <p className="text-yellow-200">{t('csessions.disabled')}</p>
        {vista.message && <p className="mt-1 text-gray-300">{vista.message}</p>}
        {vista.command && (
          <pre className="mt-2 select-all whitespace-pre-wrap break-all rounded bg-panel-bg p-2 text-xs text-gray-100">
            {vista.command}
          </pre>
        )}
      </div>
    )
  }
  return (
    <p
      role="alert"
      className="rounded border border-red-700/60 bg-red-900/20 p-3 text-sm text-red-200"
    >
      {tError(error)}
    </p>
  )
}

// Una sesión de la lista o un resultado de búsqueda.
function Row({ session, snippet, busy, onOpen, onResume }) {
  const { t } = useT()
  return (
    <li className="rounded border border-panel-border bg-panel-surface p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1 break-words font-medium text-gray-100">
          {session.title || t('csessions.untitled')}
        </span>
        <span className="text-xs text-panel-muted">{formatIsoDate(session.date)}</span>
      </div>
      <div className="mt-0.5 text-xs text-panel-muted">
        {projectName(session.project)}
        {session.n_messages > 0 &&
          ` · ${t('csessions.messages', { n: session.n_messages })}`}
      </div>
      {snippet}
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className={BOTON} onClick={onOpen}>
          {t('csessions.open')}
        </button>
        <button type="button" className={BOTON} disabled={busy} onClick={onResume}>
          {t('csessions.resume')}
        </button>
      </div>
    </li>
  )
}

function useRequest() {
  const [state, setState] = useState({ loading: false, error: null, data: null })
  // Solo vale la última petición: una respuesta lenta no pisa a otra más nueva.
  const ticket = useRef(0)
  const run = useCallback(async (fn) => {
    const mine = ++ticket.current
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fn()
      if (mine === ticket.current) setState({ loading: false, error: null, data })
    } catch (error) {
      if (mine === ticket.current) setState({ loading: false, error, data: null })
    }
  }, [])
  return [state, run]
}

function RecentPane({ project, busy, onOpen, onResume }) {
  const { t } = useT()
  const [state, run] = useRequest()
  useEffect(() => {
    run(() => api.claudeSessions(project?.id))
  }, [project?.id, run])
  const sessions = state.data?.sessions || []
  return (
    <div className="space-y-3">
      <ErrorBox error={state.error} />
      {state.loading && (
        <p className="text-sm text-panel-muted">{t('csessions.loading')}</p>
      )}
      {!state.loading && !state.error && sessions.length === 0 && (
        <p className="text-sm text-panel-muted">{t('csessions.none')}</p>
      )}
      <ul className="space-y-2">
        {sessions.map((s) => (
          <Row
            key={s.id}
            session={{ ...s, date: s.last_ts }}
            busy={busy}
            onOpen={() => onOpen(s)}
            onResume={() => onResume(s.id)}
          />
        ))}
      </ul>
    </div>
  )
}

function SearchPane({ project, busy, onOpen, onResume }) {
  const { t } = useT()
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [state, run] = useRequest()
  const [searched, setSearched] = useState(false)

  const submit = (e) => {
    e.preventDefault()
    const body = buildSearchBody(query, filters, project?.id)
    if (!body) return
    setSearched(true)
    run(() => api.claudeSessionsSearch(body))
  }
  const hits = state.data?.hits || []
  const set = (patch) => setFilters((f) => ({ ...f, ...patch }))
  const check = 'flex min-h-[2.75rem] items-center gap-2 text-sm text-gray-200'

  return (
    <div className="space-y-3">
      <form onSubmit={submit} className="space-y-3">
        <div className="flex gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('csessions.search_placeholder')}
            aria-label={t('csessions.search_placeholder')}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            className={CAMPO}
          />
          <button type="submit" className={BOTON_PRIMARIO} disabled={!query.trim()}>
            {t('csessions.search')}
          </button>
        </div>
        <details className="rounded border border-panel-border p-2">
          <summary className="min-h-[2.75rem] cursor-pointer py-2 text-sm text-panel-muted">
            {t('csessions.filters')}
          </summary>
          <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            <label className="text-sm text-gray-200">
              {t('csessions.role')}
              <select
                value={filters.role}
                onChange={(e) => set({ role: e.target.value })}
                className={`${CAMPO} mt-1`}
              >
                <option value="">{t('csessions.role_any')}</option>
                <option value="user">{t('csessions.role_user')}</option>
                <option value="assistant">{t('csessions.role_assistant')}</option>
              </select>
            </label>
            <label className="text-sm text-gray-200">
              {t('csessions.sort')}
              <select
                value={filters.sort}
                onChange={(e) => set({ sort: e.target.value })}
                className={`${CAMPO} mt-1`}
              >
                <option value="date">{t('csessions.sort_date')}</option>
                <option value="relevance">{t('csessions.sort_relevance')}</option>
              </select>
            </label>
            <fieldset className="sm:col-span-2">
              <legend className="text-sm text-gray-200">{t('csessions.kinds')}</legend>
              <div className="flex flex-wrap gap-x-4">
                {KINDS.map((k) => (
                  <label key={k} className={check}>
                    <input
                      type="checkbox"
                      className="h-5 w-5"
                      checked={filters.kinds.includes(k)}
                      onChange={() => set({ kinds: toggleKind(filters.kinds, k) })}
                    />
                    {t(`csessions.kind_${k}`)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className={check}>
              <input
                type="checkbox"
                className="h-5 w-5"
                checked={filters.regex}
                onChange={(e) => set({ regex: e.target.checked })}
              />
              {t('csessions.regex')}
            </label>
            <label className={check}>
              <input
                type="checkbox"
                className="h-5 w-5"
                checked={filters.subagents}
                onChange={(e) => set({ subagents: e.target.checked })}
              />
              {t('csessions.subagents')}
            </label>
          </div>
        </details>
      </form>
      <ErrorBox error={state.error} />
      {state.loading && (
        <p className="text-sm text-panel-muted">{t('csessions.searching')}</p>
      )}
      {searched && !state.loading && !state.error && hits.length === 0 && (
        <p className="text-sm text-panel-muted">{t('csessions.no_results')}</p>
      )}
      <ul className="space-y-2">
        {hits.map((h, i) => (
          <Row
            key={`${h.session_id}-${i}`}
            session={{
              id: h.session_id,
              title: h.title,
              project: h.project,
              date: h.ts,
              n_messages: 0,
            }}
            snippet={<ClaudeSnippet segments={h.segments} />}
            busy={busy}
            onOpen={() => onOpen({ id: h.session_id, title: h.title })}
            onResume={() => onResume(h.session_id)}
          />
        ))}
      </ul>
    </div>
  )
}

// Baja un texto como archivo desde el navegador, sin pasar por el servidor.
function downloadText(name, text) {
  const url = URL.createObjectURL(
    new Blob([text], { type: 'text/markdown;charset=utf-8' }),
  )
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function Viewer({ session, busy, onBack, onResume }) {
  const { t } = useT()
  const [messages, setMessages] = useState([])
  const [more, setMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [thinking, setThinking] = useState(false)
  const [tools, setTools] = useState(false)
  const [notice, setNotice] = useState('')
  const [manualCommand, setManualCommand] = useState('')
  const ticket = useRef(0)

  const load = useCallback(
    async (offset) => {
      const mine = ++ticket.current
      setLoading(true)
      setError(null)
      try {
        const data = await api.claudeSession(session.id, { offset, thinking, tools })
        if (mine !== ticket.current) return
        setMessages((prev) => (offset ? [...prev, ...data.messages] : data.messages))
        setMore(data.truncated)
      } catch (err) {
        if (mine === ticket.current) setError(err)
      } finally {
        if (mine === ticket.current) setLoading(false)
      }
    },
    [session.id, thinking, tools],
  )

  useEffect(() => {
    load(0)
  }, [load])

  const copyCommand = async () => {
    setNotice('')
    setManualCommand('')
    try {
      const { exists, command } = await api.claudeSessionResume(session.id)
      if (!exists) {
        setNotice(t('csessions.cwd_missing'))
        return
      }
      try {
        await navigator.clipboard.writeText(command)
        setNotice(t('csessions.copied'))
      } catch {
        // Sin portapapeles (página sin HTTPS, permiso negado): se enseña el
        // comando para copiarlo a mano.
        setManualCommand(command)
      }
    } catch (err) {
      setError(err)
    }
  }

  const exportMd = async () => {
    setNotice('')
    try {
      const text = await api.claudeSessionExport(session.id)
      downloadText(`${session.id.slice(0, 8)}.md`, text)
    } catch (err) {
      setError(err)
    }
  }

  const check = 'flex min-h-[2.75rem] items-center gap-2 text-sm text-gray-200'
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={BOTON} onClick={onBack}>
          {t('csessions.back')}
        </button>
        <button type="button" className={BOTON} onClick={copyCommand}>
          {t('csessions.copy_command')}
        </button>
        <button type="button" className={BOTON} onClick={exportMd}>
          {t('csessions.export')}
        </button>
        <button
          type="button"
          className={BOTON_PRIMARIO}
          disabled={busy}
          onClick={() => onResume(session.id)}
        >
          {t('csessions.resume_in_grid')}
        </button>
      </div>
      <h3 className="break-words text-base font-semibold text-gray-100">
        {session.title || t('csessions.untitled')}
      </h3>
      {notice && <p className="text-sm text-green-300">{notice}</p>}
      {manualCommand && (
        <input
          readOnly
          value={manualCommand}
          onFocus={(e) => e.target.select()}
          aria-label={t('csessions.copy_command')}
          className={CAMPO}
        />
      )}
      <div className="flex flex-wrap gap-x-4">
        <label className={check}>
          <input
            type="checkbox"
            className="h-5 w-5"
            checked={thinking}
            onChange={(e) => setThinking(e.target.checked)}
          />
          {t('csessions.show_thinking')}
        </label>
        <label className={check}>
          <input
            type="checkbox"
            className="h-5 w-5"
            checked={tools}
            onChange={(e) => setTools(e.target.checked)}
          />
          {t('csessions.show_tools')}
        </label>
      </div>
      <ErrorBox error={error} />
      <ol className="space-y-3">
        {messages.map((m, i) => (
          <li
            key={i}
            className={`rounded border p-3 ${
              m.role === 'user'
                ? 'border-panel-accent/50 bg-panel-accent/10'
                : 'border-panel-border bg-panel-surface'
            }`}
          >
            <div className="mb-1 text-xs text-panel-muted">
              {t(`csessions.role_${roleKey(m.role)}`)}
              {m.ts &&
                ` · ${formatIsoDate(m.ts)} ${formatTime(new Date(m.ts).getTime() / 1000)}`}
            </div>
            {m.blocks.map((b, j) => (
              <pre
                key={j}
                className={`whitespace-pre-wrap break-words font-sans text-sm ${
                  b.error ? 'text-red-300' : 'text-gray-200'
                } ${j ? 'mt-2' : ''}`}
              >
                {b.text}
              </pre>
            ))}
          </li>
        ))}
      </ol>
      {loading && <p className="text-sm text-panel-muted">{t('csessions.loading')}</p>}
      {more && !loading && (
        <button type="button" className={BOTON} onClick={() => load(messages.length)}>
          {t('csessions.load_more')}
        </button>
      )}
    </div>
  )
}

/**
 * @param {{id:string,title:string}|null} project  proyecto al que se acota, o null (global)
 * @param {() => void} onClose
 * @param {(sessionId:string, projectId:string|null) => Promise<void>} onResume
 *   abre la terminal nueva en el grid; si falla, lanza
 */
export function ClaudeSessions({ project, onClose, onResume }) {
  const { t } = useT()
  const [tab, setTab] = useState(project ? 'recent' : 'search')
  const [viewing, setViewing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      if (viewing) setViewing(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [viewing, onClose])

  const resume = async (id) => {
    setBusy(true)
    setActionError(null)
    try {
      await onResume(id, project?.id || null)
    } catch (err) {
      setActionError(err)
      setBusy(false)
    }
  }

  const tabClass = (name) =>
    `min-h-[2.75rem] flex-1 rounded px-3 text-sm font-medium ${
      tab === name ? 'bg-panel-accent text-white' : 'text-panel-muted hover:bg-panel-bg'
    }`

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col bg-panel-bg"
      role="dialog"
      aria-modal="true"
    >
      <header className="flex items-center gap-3 border-b border-panel-border px-4 py-2">
        <h2 className="min-w-0 flex-1 truncate text-base font-semibold text-gray-100">
          {project
            ? t('csessions.title_project', { title: project.title })
            : t('csessions.title')}
        </h2>
        <button type="button" className={BOTON} onClick={onClose}>
          {t('csessions.close')}
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div className="mx-auto max-w-3xl space-y-3">
          <ErrorBox error={actionError} />
          {viewing && (
            <Viewer
              session={viewing}
              busy={busy}
              onBack={() => setViewing(null)}
              onResume={resume}
            />
          )}
          {/* Las pestañas siguen montadas aunque se lea una sesión, para no
              perder la búsqueda ni la lista al volver. */}
          <div hidden={Boolean(viewing)} className="space-y-3">
            <div className="flex gap-1 rounded border border-panel-border p-1">
              {project && (
                <button
                  type="button"
                  className={tabClass('recent')}
                  onClick={() => setTab('recent')}
                >
                  {t('csessions.tab_recent')}
                </button>
              )}
              <button
                type="button"
                className={tabClass('search')}
                onClick={() => setTab('search')}
              >
                {t('csessions.tab_search')}
              </button>
              {!project && (
                <button
                  type="button"
                  className={tabClass('recent')}
                  onClick={() => setTab('recent')}
                >
                  {t('csessions.tab_recent')}
                </button>
              )}
            </div>
            <div hidden={tab !== 'recent'}>
              <RecentPane
                project={project}
                busy={busy}
                onOpen={setViewing}
                onResume={resume}
              />
            </div>
            <div hidden={tab !== 'search'}>
              <SearchPane
                project={project}
                busy={busy}
                onOpen={setViewing}
                onResume={resume}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
