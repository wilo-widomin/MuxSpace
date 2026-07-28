import React, { useEffect, useId, useRef, useState } from 'react'
import { ApiError, api } from '../api.js'
import { LANGUAGES, useT } from '../i18n/index.jsx'
import { quotePath } from '../lib/paths.js'
import { CloseIcon, Modal } from './sidebar/Modal.jsx'
import { UNASSIGNED, spaceKeyOf } from '../spaces.js'
import { LAYOUTS, LayoutIcon } from './SessionGrid.jsx'

// Rutas y comandos de ejemplo de los placeholders. NO se traducen: son
// rutas y binarios reales, no prosa. La traducción cubre solo el "p. ej."
// que los precede (ver `form.command_placeholder` y compañía).
const EXAMPLE_COMMAND = 'cd ~/proyectos/foo && nvim'
const EXAMPLE_DIR = '~/proyectos/foo'
const EXAMPLE_QUICK_COMMAND = 'htop'

// Un nombre de sesión debe ser un único segmento: la '/' rompe el routing
// REST del backend (el proxy mTLS decodifica %2F y la ruta deja de casar),
// así que la sustituimos por '_' mientras se teclea, igual que hace el backend.
function sanitizeSessionName(value) {
  return (value || '').replace(/[/\\]/g, '_')
}

// Sugiere el primer nombre "sesion-N" que no esté en uso.
//
// OJO: "sesion-N" NO se traduce. Es un identificador de tmux —el backend lo
// valida contra `_SESSION_NAME_RE` (ASCII: letras, números, '-' y '_')— y
// además queda persistido. Parece texto, pero es un dato.
function suggestName(existing) {
  const taken = new Set(existing)
  let n = 1
  while (taken.has(`sesion-${n}`)) n += 1
  return `sesion-${n}`
}

// Panel de Control (20%): catálogo de sesiones disponibles. Al hacer
// clic sobre una sesión se solicita su apertura en el grid.
export default function Sidebar({
  collapsed,
  onToggleCollapse,
  width,
  sessions,
  commands,
  projects,
  openNames,
  activeName,
  spaces,
  activeSpace,
  onSetActiveSpace,
  onCreateSpace,
  onRenameSpace,
  onDeleteSpace,
  onAssignSpace,
  loading,
  error,
  onSelect,
  onHideTile,
  onCreate,
  onRenameSession,
  onKillSession,
  onRunCommand,
  onRunProject,
  onRunProjectInNewTab,
  onSaveCommand,
  onUpdateCommand,
  onDeleteCommand,
  onSaveProject,
  onUpdateProject,
  onDeleteProject,
  onRefresh,
  layout,
  onSetLayout,
  onLogout,
}) {
  const { t, tError } = useT()
  // El espacio activo acota TODO el panel, no solo el grid: la lista de
  // sesiones muestra las de ese espacio.
  const spaceSessions = sessions.filter(
    (s) => spaceKeyOf(s) === activeSpace,
  )

  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [createError, setCreateError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // Edición en línea del nombre de una sesión.
  const [renamingName, setRenamingName] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState(null)

  // Edición en línea de un Comando de la biblioteca.
  const [editingId, setEditingId] = useState(null)
  const [editLabel, setEditLabel] = useState('')
  const [editCommand, setEditCommand] = useState('')
  const [editError, setEditError] = useState(null)
  const [savingEdit, setSavingEdit] = useState(false)

  // Estado del formulario de nueva sesión: comando a ejecutar y cwd.
  const [command, setCommand] = useState('')
  const [cwd, setCwd] = useState('')
  // `selectedPresetId` recuerda si el `command` actual vino de elegir un
  // comando de la biblioteca (frente a tecleado a mano). Se usa al guardar
  // como proyecto para decidir si hay que crear el comando primero.
  const [selectedPresetId, setSelectedPresetId] = useState(null)
  const [saveProject, setSaveProject] = useState(false)
  const [projectTitle, setProjectTitle] = useState('')

  // ---- Estado de la sección Proyectos ----
  const [projCreating, setProjCreating] = useState(false)
  // ---- Estado del formulario rápido de nuevo Comando ----
  const [cmdCreating, setCmdCreating] = useState(false)
  const [projTitle, setProjTitle] = useState('')
  const [projCwd, setProjCwd] = useState('')
  const [projCommands, setProjCommands] = useState([''])
  const [projError, setProjError] = useState(null)
  const [projSubmitting, setProjSubmitting] = useState(false)

  // Edición en línea de un Proyecto.
  const [projEditingId, setProjEditingId] = useState(null)
  const [projEditTitle, setProjEditTitle] = useState('')
  const [projEditCwd, setProjEditCwd] = useState('')
  const [projEditCommands, setProjEditCommands] = useState([''])
  const [projEditError, setProjEditError] = useState(null)
  const [projSavingEdit, setProjSavingEdit] = useState(false)

  // ---- Redimensionado manual de las secciones (arrastre de divisores) ----
  // Los altos se persisten en localStorage para que el navegador los
  // recuerde entre sesiones y no haya que reajustarlos cada vez.
  const MIN_SECTION = 56
  const HEIGHTS_KEY = 'muxspace-sidebar-heights'
  const SECTION_KEY = 'muxspace-sidebar-section'
  const readHeights = () => {
    try {
      const raw = localStorage.getItem(HEIGHTS_KEY)
      if (!raw) return null
      const parsed = JSON.parse(raw)
      let p = Number(parsed.p)
      let c = Number(parsed.c)
      if (!Number.isFinite(p) || !Number.isFinite(c)) return null
      p = Math.max(MIN_SECTION, p)
      c = Math.max(MIN_SECTION, c)
      // Salvaguarda: si la ventana es ahora más pequeña que cuando se
      // guardaron los altos, recorta para no aplastar las sesiones.
      const avail = window.innerHeight - 240
      if (Number.isFinite(avail) && p + c > avail) {
        const scale = avail / (p + c)
        p = Math.max(MIN_SECTION, Math.round(p * scale))
        c = Math.max(MIN_SECTION, Math.round(c * scale))
      }
      return { p, c }
    } catch {
      return null
    }
  }
  const initialHeights = readHeights() || { p: 160, c: 140 }
  const [projectsH, setProjectsH] = useState(initialHeights.p)
  const [commandsH, setCommandsH] = useState(initialHeights.c)
  const bodyRef = useRef(null)
  // Ref como fuente de verdad para los altos: los eventos de puntero pueden
  // dispararse varias veces antes de que React vuelva a renderizar, así
  // evitamos leer valores caducos del closure.
  const heightsRef = useRef({ p: initialHeights.p, c: initialHeights.c })

  // Persiste los altos cada vez que cambian por arrastre.
  useEffect(() => {
    try {
      localStorage.setItem(
        HEIGHTS_KEY,
        JSON.stringify({ p: projectsH, c: commandsH }),
      )
    } catch {
      // almacenamiento no disponible (modo privado, etc.): no es fatal.
    }
  }, [projectsH, commandsH])

  // Las cuatro persianas del lateral (proyectos, comandos, pegar imagen y
  // subir archivo) funcionan como acordeón: solo una abierta a la vez, así
  // ninguna se come el alto de las demás. Se recuerda entre recargas.
  const readSection = () => {
    try {
      const v = localStorage.getItem(SECTION_KEY)
      if (v === null) return 'projects'
      return v === '' ? null : v
    } catch {
      return 'projects'
    }
  }
  const [openSection, setOpenSection] = useState(readSection)
  useEffect(() => {
    try {
      localStorage.setItem(SECTION_KEY, openSection || '')
    } catch {
      // almacenamiento no disponible: no es fatal.
    }
  }, [openSection])
  const toggleSection = (name) =>
    setOpenSection((cur) => (cur === name ? null : name))
  const cmdOpen = openSection === 'commands'
  const projOpen = openSection === 'projects'

  // Divisor sesiones|sección abierta: convención estándar — al bajar el
  // divisor crece la sección de encima (Sesiones) y se encoge la de debajo.
  // Como solo hay una persiana abierta a la vez, el divisor redimensiona la
  // que esté abierta (proyectos o comandos).
  const resizeOpenSection = (dy, key) => {
    const cur = heightsRef.current
    const bodyH = bodyRef.current?.getBoundingClientRect().height
    const max = bodyH ? bodyH - MIN_SECTION : Infinity
    const next = Math.max(
      MIN_SECTION,
      Math.min(cur[key] - dy, Math.max(MIN_SECTION, max)),
    )
    heightsRef.current = { ...cur, [key]: next }
    if (key === 'p') setProjectsH(next)
    else setCommandsH(next)
  }
  const resizeProjects = (dy) => resizeOpenSection(dy, 'p')
  const resizeCommandsTop = (dy) => resizeOpenSection(dy, 'c')

  const openForm = () => {
    setNewName(suggestName(sessions.map((s) => s.name)))
    setCommand('')
    setCwd('')
    setSelectedPresetId(null)
    setSaveProject(false)
    setProjectTitle('')
    setCreateError(null)
    setCreating(true)
  }

  const closeForm = () => {
    setCreating(false)
    setCreateError(null)
  }

  const applyPreset = (e) => {
    const id = e.target.value
    if (!id) {
      setSelectedPresetId(null)
      setCommand('')
      return
    }
    const preset = commands.find((c) => c.id === id)
    if (preset) {
      setSelectedPresetId(preset.id)
      setCommand(preset.command)
    }
  }

  // Al teclear en la línea de comando, el contenido deja de provenir de la
  // biblioteca: pierde la asociación con el preset elegido.
  const onTypeCommand = (value) => {
    setSelectedPresetId(null)
    setCommand(value)
  }

  const submitCreate = async (e) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name || submitting) return
    setSubmitting(true)
    setCreateError(null)
    try {
      // Si el usuario marcó guardar como proyecto, persiste el proyecto
      // antes de crear la sesión (incluso si falla la sesión, el proyecto
      // queda guardado para reintentar). Cuando el comando fue tecleado
      // (no elegido de la biblioteca) se crea primero el comando en la
      // biblioteca y luego el proyecto con ese comando asociado.
      const cmdLine = command.trim()
      if (saveProject && cmdLine) {
        const title = projectTitle.trim() || name
        const cwdVal = cwd.trim() || null
        if (!selectedPresetId) {
          await onSaveCommand('', cmdLine)
        }
        await onSaveProject(title, cwdVal, [cmdLine])
      }
      const cmd = cmdLine
        ? { command: cmdLine, cwd: cwd.trim() || null }
        : null
      await onCreate(name, cmd)
      setCreating(false)
    } catch (err) {
      setCreateError(
        err instanceof ApiError ? tError(err) : t('form.create_session_failed'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  const killSession = (s) => {
    onKillSession(s.name)
  }

  const cancelRename = () => {
    setRenamingName(null)
    setRenameError(null)
  }

  const startRename = (s) => {
    setRenamingName(s.name)
    setRenameValue(s.name)
    setRenameError(null)
  }

  const submitRename = async (e, oldName) => {
    e.preventDefault()
    const newName = renameValue.trim()
    if (!newName) return
    if (newName === oldName) {
      cancelRename()
      return
    }
    try {
      await onRenameSession(oldName, newName)
      cancelRename()
    } catch (err) {
      setRenameError(
        err instanceof ApiError ? tError(err) : t('form.rename_session_failed'),
      )
    }
  }

  // ---- Comandos: edición en línea ----
  const startEdit = (c) => {
    setEditingId(c.id)
    setEditLabel(c.label)
    setEditCommand(c.command)
    setEditError(null)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditError(null)
  }

  const submitEdit = async (e, id) => {
    e.preventDefault()
    const command = editCommand.trim()
    if (!command || savingEdit) return
    setSavingEdit(true)
    setEditError(null)
    try {
      await onUpdateCommand(id, editLabel.trim(), command)
      setEditingId(null)
    } catch (err) {
      setEditError(
        err instanceof ApiError ? tError(err) : t('form.save_command_failed'),
      )
    } finally {
      setSavingEdit(false)
    }
  }

  const removeCommand = async (id, label) => {
    if (!window.confirm(t('sidebar.confirm_delete_command', { label }))) return
    try {
      await onDeleteCommand(id)
    } catch {
      // Error no fatal: el listado se refresca solo.
    }
  }

  // ---- Comandos: formulario rápido ----
  const openCmdForm = () => setCmdCreating(true)
  const closeCmdForm = () => setCmdCreating(false)

  // ---- Proyectos: crear ----
  const openProjForm = () => {
    setProjTitle('')
    setProjCwd('')
    setProjCommands([''])
    setProjError(null)
    setProjCreating(true)
  }

  const closeProjForm = () => {
    setProjCreating(false)
    setProjError(null)
  }

  const setProjCommandAt = (i, value) => {
    setProjCommands((cur) => cur.map((c, idx) => (idx === i ? value : c)))
  }

  const addProjCommand = () => setProjCommands((cur) => [...cur, ''])
  const removeProjCommand = (i) =>
    setProjCommands((cur) => cur.filter((_, idx) => idx !== i))

  const submitProjCreate = async (e) => {
    e.preventDefault()
    const title = projTitle.trim()
    const cmds = projCommands.map((c) => c.trim()).filter(Boolean)
    if (!title || projSubmitting) return
    if (cmds.length === 0) {
      setProjError(t('form.need_one_command'))
      return
    }
    setProjSubmitting(true)
    setProjError(null)
    try {
      await onSaveProject(title, projCwd.trim() || null, cmds)
      setProjCreating(false)
    } catch (err) {
      setProjError(
        err instanceof ApiError ? tError(err) : t('form.save_project_failed'),
      )
    } finally {
      setProjSubmitting(false)
    }
  }

  // ---- Proyectos: edición en línea ----
  const startProjEdit = (p) => {
    setProjEditingId(p.id)
    setProjEditTitle(p.title)
    setProjEditCwd(p.cwd || '')
    setProjEditCommands(p.commands.length ? [...p.commands] : [''])
    setProjEditError(null)
  }

  const cancelProjEdit = () => {
    setProjEditingId(null)
    setProjEditError(null)
  }

  const setProjEditCommandAt = (i, value) => {
    setProjEditCommands((cur) => cur.map((c, idx) => (idx === i ? value : c)))
  }
  const addProjEditCommand = () => setProjEditCommands((cur) => [...cur, ''])
  const removeProjEditCommand = (i) =>
    setProjEditCommands((cur) => cur.filter((_, idx) => idx !== i))

  const submitProjEdit = async (e, id) => {
    e.preventDefault()
    const title = projEditTitle.trim()
    const cmds = projEditCommands.map((c) => c.trim()).filter(Boolean)
    if (!title || projSavingEdit) return
    if (cmds.length === 0) {
      setProjEditError(t('form.need_one_command'))
      return
    }
    setProjSavingEdit(true)
    setProjEditError(null)
    try {
      await onUpdateProject(id, title, projEditCwd.trim() || null, cmds)
      setProjEditingId(null)
    } catch (err) {
      setProjEditError(
        err instanceof ApiError ? tError(err) : t('form.save_project_failed'),
      )
    } finally {
      setProjSavingEdit(false)
    }
  }

  const removeProject = async (id, title) => {
    if (!window.confirm(t('sidebar.confirm_delete_project', { title }))) return
    try {
      await onDeleteProject(id)
    } catch {
      // Error no fatal: el listado se refresca solo.
    }
  }

  const runTargetTitle = () =>
    activeName
      ? t('sidebar.run_in_terminal', { name: activeName })
      : t('sidebar.run_in_new_session')

  // Estado colapsado: rail estrecho con un único botón para expandir, de
  // modo que el grid de terminales ocupa casi toda la pantalla.
  if (collapsed) {
    return (
      <aside className="flex h-full w-12 shrink-0 flex-col items-center border-r border-panel-border bg-panel-surface py-3 text-gray-100">
        <button
          onClick={onToggleCollapse}
          title={t('sidebar.expand')}
          className="rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
        >
          <ChevronRightIcon />
        </button>
        <button
          onClick={() => {
            onToggleCollapse()
            openForm()
          }}
          title={t('sidebar.new_session')}
          className="mt-2 rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
        >
          <PlusIcon />
        </button>
        {/* Sin sitio para los tres botones: aquí uno solo que rota de modo. */}
        <button
          onClick={() =>
            onSetLayout(LAYOUTS[(LAYOUTS.indexOf(layout) + 1) % LAYOUTS.length])
          }
          title={t(`grid.layout_${layout}`)}
          aria-label={t(`grid.layout_${layout}`)}
          className="mt-2 rounded p-1.5 text-panel-accent transition hover:bg-panel-bg"
        >
          <LayoutIcon mode={layout} />
        </button>
      </aside>
    )
  }

  return (
    <aside
      style={{ width }}
      className="flex h-full shrink-0 flex-col border-r border-panel-border bg-panel-surface text-gray-100"
    >
      <header className="flex items-center justify-between border-b border-panel-border bg-black px-4 py-3">
        <h1 className="text-base font-semibold">{t('app.brand')}</h1>
        <div className="flex items-center gap-1">
          {LAYOUTS.map((mode) => (
            <button
              key={mode}
              onClick={() => onSetLayout(mode)}
              title={t(`grid.layout_${mode}`)}
              aria-label={t(`grid.layout_${mode}`)}
              aria-pressed={layout === mode}
              className={`rounded p-1.5 transition hover:bg-panel-bg ${
                layout === mode
                  ? 'text-panel-accent'
                  : 'text-panel-muted hover:text-gray-100'
              }`}
            >
              <LayoutIcon mode={mode} />
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-panel-border" />
          <button
            onClick={openForm}
            title={t('sidebar.new_session')}
            className="rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <PlusIcon />
          </button>
          <button
            onClick={onRefresh}
            title={t('sidebar.refresh')}
            className="rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <RefreshIcon />
          </button>
          <button
            onClick={onToggleCollapse}
            title={t('sidebar.collapse')}
            className="rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <ChevronLeftIcon />
          </button>
        </div>
      </header>

      <SpacesBar
        spaces={spaces}
        sessions={sessions}
        activeSpace={activeSpace}
        onSetActiveSpace={onSetActiveSpace}
        onCreateSpace={onCreateSpace}
        onRenameSpace={onRenameSpace}
        onDeleteSpace={onDeleteSpace}
      />

      <div ref={bodyRef} className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading && (
          <p className="px-2 py-4 text-sm text-panel-muted">{t('app.loading')}</p>
        )}

        {error && (
          <p className="mx-1 my-2 rounded bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        {!loading && !error && spaceSessions.length === 0 && (
          <p className="px-2 py-4 text-sm text-panel-muted">
            {sessions.length === 0
              ? t('sidebar.no_sessions')
              : t('sidebar.space_empty')}
          </p>
        )}

        <ul className="space-y-1">
          {spaceSessions.map((s) => {
            const isOpen = openNames.includes(s.name)
            const isRenaming = renamingName === s.name
            return (
              <li key={s.name}>
                {isRenaming ? (
                  <form
                    onSubmit={(e) => submitRename(e, s.name)}
                    className="flex items-center gap-1 rounded bg-panel-bg px-2 py-1"
                  >
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) =>
                        setRenameValue(sanitizeSessionName(e.target.value))
                      }
                      onFocus={(e) => e.target.select()}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') cancelRename()
                      }}
                      className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-sm outline-none focus:border-panel-accent"
                    />
                    <button
                      type="submit"
                      title={t('sidebar.save_name')}
                      className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-surface hover:text-green-400"
                    >
                      <CheckIcon />
                    </button>
                    <button
                      type="button"
                      onClick={cancelRename}
                      title={t('sidebar.cancel')}
                      className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-surface hover:text-gray-100"
                    >
                      <CloseIcon />
                    </button>
                  </form>
                ) : (
                  <div
                    className={`group flex w-full items-center rounded text-sm transition ${
                      isOpen ? 'bg-panel-bg' : 'hover:bg-panel-bg'
                    }`}
                  >
                    <button
                      onClick={() => onSelect(s.name)}
                      className="flex min-w-0 flex-1 items-center justify-between px-3 py-2 text-left"
                      title={isOpen ? t('sidebar.bring_to_front') : t('sidebar.open')}
                    >
                      <span className="flex items-center gap-2 truncate">
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${
                            s.attached ? 'bg-green-400' : 'bg-panel-muted'
                          }`}
                          title={
                            s.attached
                              ? t('sidebar.attached')
                              : t('sidebar.detached')
                          }
                        />
                        <span
                          className={`truncate font-medium ${
                            isOpen ? 'text-panel-muted' : ''
                          }`}
                        >
                          {s.name}
                        </span>
                      </span>
                      <span className="ml-2 shrink-0 text-xs text-panel-muted">
                        {isOpen
                          ? t('sidebar.state_open')
                          : t('sidebar.windows', { count: s.windows })}
                      </span>
                    </button>
                    <MoveToSpace
                      session={s}
                      spaces={spaces}
                      onAssign={onAssignSpace}
                    />
                    <button
                      onClick={() => startRename(s)}
                      title={t('sidebar.rename_session')}
                      className="shrink-0 rounded p-1.5 text-panel-muted opacity-0 transition hover:bg-panel-surface hover:text-gray-100 group-hover:opacity-100"
                    >
                      <PencilIcon />
                    </button>
                    <button
                      onClick={() => killSession(s)}
                      title={t('sidebar.kill_session')}
                      className="mr-1 shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-red-500/20 hover:text-red-400"
                    >
                      <DoorIcon />
                    </button>
                    {isOpen && (
                      <button
                        onClick={() => onHideTile(s.name)}
                        title={t('sidebar.hide_tile')}
                        className="mr-1 shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-panel-surface hover:text-gray-100"
                      >
                        <CloseIcon />
                      </button>
                    )}
                  </div>
                )}
                {isRenaming && renameError && (
                  <p className="mt-1 rounded bg-red-500/10 px-2 py-1 text-xs text-red-400">
                    {renameError}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      </div>

      {/* Secciones fijas al fondo: Proyectos arriba, Comandos debajo. Cada
          una se pliega por separado con su propio botón. */}
      {(projOpen || cmdOpen) && (
        <Resizer onDrag={projOpen ? resizeProjects : resizeCommandsTop} />
      )}

      <div className="shrink-0 border-t border-panel-border flex flex-col-reverse">
        {/* ---------------- Comandos (una línea) ---------------- */}
        <div
          style={cmdOpen ? { height: commandsH } : undefined}
          className={`min-h-0 border-t border-panel-border p-2 ${
            cmdOpen ? 'overflow-y-auto' : ''
          }`}
        >
          {/* El "+" va pegado al título; el desplegable, alineado a la
              derecha como en las demás persianas del lateral. */}
          <div className="flex items-center gap-1 px-2 py-1">
            <button
              onClick={() => toggleSection('commands')}
              className="flex min-w-0 items-center text-xs uppercase tracking-wide text-panel-muted transition hover:text-gray-100"
            >
              <span className="truncate">{t('sidebar.commands')}</span>
            </button>
            <button
              onClick={openCmdForm}
              title={t('sidebar.new_command')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
            >
              <PlusIcon />
            </button>
            <button
              onClick={() => toggleSection('commands')}
              title={t('sidebar.commands')}
              className="ml-auto shrink-0 rounded text-panel-muted transition hover:text-gray-100"
            >
              <SectionCaret open={cmdOpen} />
            </button>
          </div>
          {cmdOpen && (
          <>
          <p className="px-2 pb-1 text-[11px] text-panel-muted/70">
            {t('sidebar.commands_hint')}
          </p>
          <ul className="space-y-0.5">
            {commands.map((c) => (
              <li
                key={c.id}
                className="group flex items-center gap-1 rounded px-2 py-1 text-xs text-panel-muted hover:bg-panel-bg"
              >
                <button
                  onClick={(e) => {
                    e.currentTarget.blur()
                    onRunCommand(c)
                  }}
                  title={runTargetTitle()}
                  className="shrink-0 rounded p-0.5 text-panel-muted transition hover:bg-panel-surface hover:text-green-400"
                >
                  <PlayIcon />
                </button>
                <span className="min-w-0 flex-1 truncate" title={c.command}>
                  {c.label}
                </span>
                <button
                  onClick={() => startEdit(c)}
                  title={t('sidebar.edit_command')}
                  className="shrink-0 rounded p-0.5 text-panel-muted opacity-0 transition hover:bg-panel-surface hover:text-gray-100 group-hover:opacity-100"
                >
                  <PencilIcon />
                </button>
                <button
                  onClick={() => removeCommand(c.id, c.label)}
                  title={t('sidebar.delete_command')}
                  className="shrink-0 rounded p-0.5 opacity-0 transition hover:bg-panel-surface hover:text-red-400 group-hover:opacity-100"
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
          </>
          )}
        </div>

        {/* ---------------- Proyectos (dir + secuencia) ---------------- */}
        <div
          style={projOpen ? { height: projectsH } : undefined}
          className={`min-h-0 p-2 ${projOpen ? 'overflow-y-auto' : ''}`}
        >
          <div className="flex items-center gap-1 px-2 py-1">
            <button
              onClick={() => toggleSection('projects')}
              className="flex min-w-0 items-center text-xs uppercase tracking-wide text-panel-muted transition hover:text-gray-100"
            >
              <span className="truncate">{t('sidebar.projects')}</span>
            </button>
            <button
              onClick={openProjForm}
              title={t('sidebar.new_project')}
              className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
            >
              <PlusIcon />
            </button>
            <button
              onClick={() => toggleSection('projects')}
              title={t('sidebar.projects')}
              className="ml-auto shrink-0 rounded text-panel-muted transition hover:text-gray-100"
            >
              <SectionCaret open={projOpen} />
            </button>
          </div>
          {projOpen && (
          <>
          <p className="px-2 pb-1 text-[11px] text-panel-muted/70">
            {t('sidebar.projects_hint')}
          </p>

          <ul className="space-y-0.5">
            {projects.map((p) => (
              <li
                key={p.id}
                className="group rounded px-2 py-1 text-xs text-panel-muted hover:bg-panel-bg"
              >
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => {
                      e.currentTarget.blur()
                      onRunProject(p.id)
                    }}
                    title={t('sidebar.run_project')}
                    className="shrink-0 rounded p-0.5 text-panel-muted transition hover:bg-panel-surface hover:text-green-400"
                  >
                    <PlayIcon />
                  </button>
                  <button
                    onClick={(e) => {
                      e.currentTarget.blur()
                      onRunProjectInNewTab(p.id)
                    }}
                    title={t('sidebar.run_project_new_tab')}
                    className="shrink-0 rounded p-0.5 text-panel-muted transition hover:bg-panel-surface hover:text-green-400"
                  >
                    <ExternalLinkIcon />
                  </button>
                  <span
                    className="min-w-0 flex-1 truncate font-medium text-gray-100"
                    title={[p.title, p.cwd, ...p.commands].filter(Boolean).join(' · ')}
                  >
                    {p.title}
                  </span>
                  <button
                    onClick={() => startProjEdit(p)}
                    title={t('sidebar.edit_project')}
                    className="shrink-0 rounded p-0.5 text-panel-muted opacity-0 transition hover:bg-panel-surface hover:text-gray-100 group-hover:opacity-100"
                  >
                    <PencilIcon />
                  </button>
                  <button
                    onClick={() => removeProject(p.id, p.title)}
                    title={t('sidebar.delete_project')}
                    className="shrink-0 rounded p-0.5 opacity-0 transition hover:bg-panel-surface hover:text-red-400 group-hover:opacity-100"
                  >
                    <TrashIcon />
                  </button>
                </div>
              </li>
            ))}
          </ul>
          </>
          )}
        </div>
      </div>
      </div>

      <PasteForClaude
        open={openSection === 'paste'}
        onToggle={() => toggleSection('paste')}
      />

      <UploadFiles
        open={openSection === 'upload'}
        onToggle={() => toggleSection('upload')}
      />

      <footer className="flex items-center justify-between gap-2 border-t border-panel-border bg-black px-4 py-3">
        <button
          onClick={onLogout}
          className="text-xs text-panel-muted transition hover:text-gray-100"
        >
          {t('sidebar.logout')}
        </button>
        <LanguagePicker />
      </footer>

      {/* ---------------- Modales (formularios) ---------------- */}
      {creating && (
        <Modal title={t('form.new_session_title')} onClose={closeForm}>
          <form onSubmit={submitCreate}>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.session_name_label')}
            </label>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(sanitizeSessionName(e.target.value))}
              onFocus={(e) => e.target.select()}
              className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mt-1 text-xs text-panel-muted">
              {t('form.session_name_hint')}
            </p>

            <label className="mb-1 mt-3 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.start_command_label')}
            </label>
            {commands.length > 0 && (
              <select
                onChange={applyPreset}
                value={selectedPresetId || ''}
                className="mb-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
              >
                <option value="">{t('form.library_pick')}</option>
                {commands.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            )}
            <input
              value={command}
              onChange={(e) => onTypeCommand(e.target.value)}
              placeholder={t('form.command_placeholder', {
                example: EXAMPLE_COMMAND,
              })}
              className="mb-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />

            <DirectoryInput
              value={cwd}
              onChange={setCwd}
              placeholder={t('form.cwd_placeholder')}
              className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />

            <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-panel-muted">
              <input
                type="checkbox"
                checked={saveProject}
                onChange={(e) => setSaveProject(e.target.checked)}
                className="accent-panel-accent"
              />
              {t('form.save_as_project')}
            </label>
            {saveProject && command.trim() && (
              <input
                value={projectTitle}
                onChange={(e) => setProjectTitle(sanitizeSessionName(e.target.value))}
                placeholder={t('form.project_title_default_placeholder')}
                className="mt-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
              />
            )}

            <button
              type="submit"
              disabled={submitting}
              className="mt-3 w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
            >
              {submitting ? t('form.creating') : t('form.create_session')}
            </button>
            {createError && (
              <p className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-xs text-red-400">
                {createError}
              </p>
            )}
          </form>
        </Modal>
      )}

      {cmdCreating && (
        <Modal title={t('form.new_command_title')} onClose={closeCmdForm}>
          <QuickCommandForm onSave={onSaveCommand} onClose={closeCmdForm} />
        </Modal>
      )}

      {editingId && (
        <Modal title={t('form.edit_command_title')} onClose={cancelEdit}>
          <form onSubmit={(e) => submitEdit(e, editingId)}>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.name_optional_label')}
            </label>
            <input
              autoFocus
              value={editLabel}
              onChange={(e) => setEditLabel(e.target.value)}
              placeholder={t('form.name_optional_placeholder')}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.command_label')}
            </label>
            <input
              value={editCommand}
              onChange={(e) => setEditCommand(e.target.value)}
              placeholder={t('form.command_only_placeholder')}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <button
              type="submit"
              disabled={savingEdit}
              className="w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
            >
              {savingEdit ? t('form.saving') : t('form.save')}
            </button>
            {editError && (
              <p className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-xs text-red-400">
                {editError}
              </p>
            )}
          </form>
        </Modal>
      )}

      {projCreating && (
        <Modal title={t('form.new_project_title')} onClose={closeProjForm} panelClassName="max-w-lg">
          <form onSubmit={submitProjCreate}>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.title_label')}
            </label>
            <input
              autoFocus
              value={projTitle}
              onChange={(e) => setProjTitle(sanitizeSessionName(e.target.value))}
              placeholder={t('form.project_title_placeholder')}
              className="mb-1 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-3 text-xs text-panel-muted">
              {t('form.project_title_hint')}
            </p>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.directory_label')}
            </label>
            <DirectoryInput
              value={projCwd}
              onChange={setProjCwd}
              placeholder={t('form.directory_placeholder', {
                example: EXAMPLE_DIR,
              })}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-1 text-xs uppercase tracking-wide text-panel-muted">
              {t('form.commands_in_order')}
            </p>
            {projCommands.map((cmd, i) => (
              <div key={i} className="mb-1 flex items-center gap-1">
                <CommandSelect
                  value={cmd}
                  onChange={(v) => setProjCommandAt(i, v)}
                  commands={commands}
                />
                {projCommands.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeProjCommand(i)}
                    title={t('form.remove')}
                    className="shrink-0 rounded p-0.5 text-panel-muted transition hover:text-red-400"
                  >
                    <CloseIcon />
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={addProjCommand}
              className="mb-3 text-xs text-panel-muted transition hover:text-panel-accent"
            >
              {t('form.add_command')}
            </button>
            <button
              type="submit"
              disabled={projSubmitting}
              className="w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
            >
              {projSubmitting ? t('form.saving') : t('form.save_project')}
            </button>
            {projError && (
              <p className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-xs text-red-400">
                {projError}
              </p>
            )}
          </form>
        </Modal>
      )}

      {projEditingId && (
        <Modal title={t('form.edit_project_title')} onClose={cancelProjEdit} panelClassName="max-w-lg">
          <form onSubmit={(e) => submitProjEdit(e, projEditingId)}>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.title_label')}
            </label>
            <input
              autoFocus
              value={projEditTitle}
              onChange={(e) => setProjEditTitle(sanitizeSessionName(e.target.value))}
              placeholder={t('form.title_placeholder')}
              className="mb-1 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-3 text-xs text-panel-muted">
              {t('form.project_title_hint')}
            </p>
            <label className="mb-1 block text-xs uppercase tracking-wide text-panel-muted">
              {t('form.directory_label')}
            </label>
            <DirectoryInput
              value={projEditCwd}
              onChange={setProjEditCwd}
              placeholder={t('form.directory_optional_placeholder')}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-1 text-xs uppercase tracking-wide text-panel-muted">
              {t('form.commands_in_order')}
            </p>
            {projEditCommands.map((cmd, i) => (
              <div key={i} className="mb-1 flex items-center gap-1">
                <CommandSelect
                  value={cmd}
                  onChange={(v) => setProjEditCommandAt(i, v)}
                  commands={commands}
                />
                {projEditCommands.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeProjEditCommand(i)}
                    title={t('form.remove')}
                    className="shrink-0 rounded p-0.5 text-panel-muted transition hover:text-red-400"
                  >
                    <CloseIcon />
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={addProjEditCommand}
              className="mb-3 text-xs text-panel-muted transition hover:text-panel-accent"
            >
              {t('form.add_command')}
            </button>
            <button
              type="submit"
              disabled={projSavingEdit}
              className="w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
            >
              {projSavingEdit ? t('form.saving') : t('form.save')}
            </button>
            {projEditError && (
              <p className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-xs text-red-400">
                {projEditError}
              </p>
            )}
          </form>
        </Modal>
      )}
    </aside>
  )
}

// <input> de directorio con autocompletado: mientras el usuario escribe
// (o al ganar el foco) pide al backend las subcarpetas que coinciden con el
// prefijo bajo las raíces configuradas (ver `MUXSPACE_DIR_SUGGESTION_ROOTS`
// y el endpoint /api/dir-suggestions). Las muestra en un <datalist> nativo.
// Barra de espacios: elige cuál mira ESTA pestaña y permite crear,
// renombrar y borrar. Dos entradas del selector no son espacios reales:
// «Todas» (vista sin filtrar) y «Sin asignar» (las sesiones que no están
// en ningún espacio, p. ej. las creadas fuera del panel); por eso ninguna
// se puede renombrar ni borrar.
function SpacesBar({
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

// Mueve una sesión a otro espacio. Un <select> nativo en vez de un menú
// propio: es lo que mejor funciona con el dedo, y este panel se usa también
// desde el móvil. En la vista «Todas» se muestra siempre (hace de etiqueta
// de a qué espacio pertenece); dentro de un espacio concreto sería
// redundante, así que solo aparece al pasar por encima.
function MoveToSpace({ session, spaces, onAssign }) {
  const { t, tError } = useT()
  const [error, setError] = useState(null)
  const value = spaceKeyOf(session)

  const change = async (e) => {
    setError(null)
    try {
      await onAssign(session.name, e.target.value)
    } catch (err) {
      setError(tError(err))
    }
  }

  return (
    <select
      value={value}
      onChange={change}
      title={error || t('spaces.move')}
      className={`mr-1 max-w-[7rem] shrink-0 truncate rounded border border-transparent bg-transparent px-1 py-0.5 text-xs opacity-0 outline-none transition hover:border-panel-border focus:border-panel-accent focus:opacity-100 group-hover:opacity-100 ${
        error ? 'text-red-400' : 'text-panel-muted'
      }`}
    >
      <option value={UNASSIGNED}>{t('spaces.unassigned')}</option>
      {spaces.map((s) => (
        <option key={s.id} value={s.id}>
          {s.title}
        </option>
      ))}
    </select>
  )
}

function DirectoryInput({ value, onChange, placeholder, className }) {
  const listId = useId()
  const [items, setItems] = useState([])
  const timer = useRef(null)
  const lastQuery = useRef('')

  const fetchSuggestions = (q) => {
    api
      .dirSuggestions(q)
      .then(setItems)
      .catch(() => setItems([]))
  }

  // Debounce al escribir: evita bombardear al backend con cada tecla.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    if (value === lastQuery.current) return
    timer.current = setTimeout(() => {
      lastQuery.current = value
      fetchSuggestions(value)
    }, 180)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [value])

  return (
    <>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={(e) => {
          e.target.select()
          fetchSuggestions(value)
        }}
        placeholder={placeholder}
        list={listId}
        className={className}
      />
      <datalist id={listId}>
        {items.map((it) => (
          <option key={it} value={it} />
        ))}
      </datalist>
    </>
  )
}

// <select> para elegir un comando de la biblioteca al componer un proyecto.
// El valor almacenado es la propia línea de comando (no el id), de modo que
// el proyecto queda como una secuencia autónoma de comandos.
function CommandSelect({ value, onChange, commands }) {
  const { t } = useT()
  const exists = commands.some((c) => c.command === value)
  return (
    <select
      value={exists ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-xs outline-none focus:border-panel-accent"
    >
      <option value="">{t('form.pick_command')}</option>
      {commands.map((c) => (
        <option key={c.id} value={c.command}>
          {c.label}
        </option>
      ))}
      {!exists && value && (
        // El comando guardado ya no está en la biblioteca: lo mostramos
        // igual para no perderlo al editar.
        <option value={value}>{value}</option>
      )}
    </select>
  )
}

// Formulario compacto para añadir un Comando de una sola línea. Se muestra
// cuando el padre lo abre (botón "+" de la cabecera "Comandos"); al guardar
// o cancelar avisa al padre para que lo cierre.
function QuickCommandForm({ onSave, onClose }) {
  const { t, tError } = useT()
  const [label, setLabel] = useState('')
  const [command, setCommand] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const cmd = command.trim()
    if (!cmd || submitting) return
    setSubmitting(true)
    setError(null)
    try {
      await onSave(label.trim(), cmd)
      setLabel('')
      setCommand('')
      onClose()
    } catch (err) {
      setError(
        err instanceof ApiError ? tError(err) : t('form.save_command_failed'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={t('form.name_optional_placeholder')}
        className="mb-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
      />
      <input
        value={command}
        onChange={(e) => setCommand(e.target.value)}
        placeholder={t('form.quick_command_placeholder', {
          example: EXAMPLE_QUICK_COMMAND,
        })}
        className="mb-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
      />
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
      >
        {submitting ? t('form.saving') : t('form.save')}
      </button>
      {error && (
        <p className="mt-2 rounded bg-red-500/10 px-2 py-1.5 text-xs text-red-400">
          {error}
        </p>
      )}
    </form>
  )
}

// Selector de idioma del pie. Los nombres van en su propio idioma a
// propósito: una lista traducida al idioma ACTUAL no le sirve a quien no
// entiende el idioma actual y quiere salir de él.
function LanguagePicker() {
  const { lang, setLang, t } = useT()
  return (
    <select
      value={lang}
      onChange={(e) => setLang(e.target.value)}
      title={t('lang.label')}
      aria-label={t('lang.label')}
      className="shrink-0 rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-panel-muted outline-none transition hover:border-panel-border focus:border-panel-accent"
    >
      {LANGUAGES.map((l) => (
        <option key={l.code} value={l.code}>
          {l.label}
        </option>
      ))}
    </select>
  )
}

// Divisor arrastrable entre dos secciones del sidebar. `orientation`:
// 'horizontal' (separador entre paneles apilados en vertical, se arrastra
// arriba/abajo) o 'vertical' (separador entre paneles en fila, se arrastra
// izquierda/derecha). Al arrastrar emite el delta acumulado desde el último
// evento de puntero; el padre decide cómo repartir los píxeles entre las
// secciones colindantes. La barra visible mide 3px, pero la zona de agarre es
// mayor para que sea fácil agarrarla con el ratón.
export function Resizer({ onDrag, orientation = 'horizontal' }) {
  const horizontal = orientation === 'horizontal'
  const onPointerDown = (e) => {
    e.preventDefault()
    let last = horizontal ? e.clientY : e.clientX
    const move = (ev) => {
      const cur = horizontal ? ev.clientY : ev.clientX
      const d = cur - last
      last = cur
      if (d) onDrag(d)
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.classList.remove('muxspace-resizing')
      document.body.classList.remove('muxspace-resizing-col')
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    document.body.classList.add(
      horizontal ? 'muxspace-resizing' : 'muxspace-resizing-col',
    )
  }
  return horizontal ? (
    <div className="relative z-10 h-[3px] shrink-0 bg-panel-border">
      <div
        onPointerDown={onPointerDown}
        className="absolute inset-x-0 -inset-y-1.5 cursor-row-resize transition-colors hover:bg-panel-accent/50"
      />
    </div>
  ) : (
    <div className="relative z-10 h-full w-[3px] shrink-0 bg-panel-border">
      <div
        onPointerDown={onPointerDown}
        className="absolute inset-y-0 -inset-x-1.5 cursor-col-resize transition-colors hover:bg-panel-accent/50"
      />
    </div>
  )
}

// Caja "Pegar imagen para Claude": apaño para compartir capturas. El usuario
// hace clic en el área y pega (Ctrl+V); la imagen se sube al backend, que la
// guarda en disco. Debajo se muestra una tira con las últimas capturas (el
// backend conserva solo las 5 más recientes): al hacer clic en cualquiera se
// copia su ruta absoluta para poder dársela a Claude. También admite elegir
// un fichero.
// Triángulo de plegar/desplegar de las persianas del lateral. Caja de tamaño
// fijo para que los cuatro queden del mismo tamaño y a la misma altura.
function SectionCaret({ open }) {
  return (
    <span className="flex h-[21px] w-[21px] shrink-0 items-center justify-center text-[21px] leading-none">
      {open ? '▾' : '▸'}
    </span>
  )
}

function PasteForClaude({ open, onToggle }) {
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
              <p className="mt-2 text-xs text-panel-muted">
                {t('paste.recent')}
              </p>
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

// Subir archivos a una carpeta que el usuario elige con un navegador tipo
// explorador (DirBrowserModal). A diferencia de "pegar imagen", el destino
// es una carpeta REAL del usuario y los archivos no se borran nunca: solo
// guardamos el historial de las últimas 5 subidas para recopiar su ruta.
function UploadFiles({ open, onToggle }) {
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

  // Al abrir: cargamos el historial y, si aún no hay carpeta elegida, pedimos
  // la carpeta por defecto (la primera raíz configurada) para tener destino.
  useEffect(() => {
    if (!open) return
    refreshUploads()
    if (destDir === null) {
      api
        .dirBrowse('')
        .then((r) => setDestDir(r.path))
        .catch(() => {})
    }
  }, [open])

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
                <p className="mt-2 text-xs text-panel-muted">
                  {t('upload.recent')}
                </p>
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
            setBrowserOpen(false)
          }}
        />
      )}
    </>
  )
}

// Navegador de carpetas tipo explorador: entra en subcarpetas con clic, sube
// un nivel, crea carpetas nuevas y confirma el destino con "Guardar aquí".
// Solo se mueve dentro de las raíces configuradas en el backend.
function DirBrowserModal({ initialPath, onClose, onPick }) {
  const { t, tError } = useT()
  const [cur, setCur] = useState(initialPath || '')
  const [parent, setParent] = useState(null)
  const [dirs, setDirs] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  async function load(path) {
    setBusy(true)
    setError(null)
    try {
      const r = await api.dirBrowse(path)
      setCur(r.path)
      setParent(r.parent)
      setDirs(r.dirs)
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.browse_failed'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load(initialPath || '')
    // Solo al montar: la navegación posterior la disparan los clics.
  }, [])

  async function submitNewFolder(e) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    setError(null)
    try {
      const r = await api.dirCreate(cur, name)
      setCreating(false)
      setNewName('')
      await load(r.path) // entramos en la carpeta recién creada
    } catch (err) {
      setError(err instanceof ApiError ? tError(err) : t('upload.create_failed'))
      setBusy(false)
    }
  }

  return (
    <Modal title={t('upload.browser_title')} onClose={onClose} panelClassName="max-w-lg">
      <div className="flex items-center gap-2">
        <button
          onClick={() => parent !== null && load(parent)}
          disabled={parent === null || busy}
          title={t('upload.up')}
          className="shrink-0 rounded border border-panel-border px-2 py-1 text-sm text-panel-muted transition enabled:hover:border-panel-accent enabled:hover:text-gray-100 disabled:opacity-40"
        >
          ↰
        </button>
        <code className="min-w-0 flex-1 truncate rounded bg-black/30 px-2 py-1 text-xs text-gray-200">
          {cur || '—'}
        </code>
      </div>

      <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto">
        {dirs.length === 0 && !busy && (
          <li className="px-2 py-1 text-xs text-panel-muted">
            {t('upload.empty_dir')}
          </li>
        )}
        {dirs.map((d) => (
          <li key={d}>
            <button
              onClick={() => load(d)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-gray-100 transition hover:bg-panel-bg"
            >
              <span className="shrink-0 text-panel-muted">
                <FolderIcon />
              </span>
              <span className="min-w-0 truncate">{d.split('/').pop() || d}</span>
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}

      <div className="mt-3 border-t border-panel-border pt-3">
        {creating ? (
          <form onSubmit={submitNewFolder} className="flex items-center gap-2">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={t('upload.new_folder_name')}
              className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-xs text-gray-100 outline-none focus:border-panel-accent"
            />
            <button
              type="submit"
              disabled={busy || !newName.trim()}
              className="shrink-0 rounded bg-panel-accent px-2 py-1 text-xs text-white transition disabled:opacity-40"
            >
              {t('upload.create')}
            </button>
            <button
              type="button"
              onClick={() => {
                setCreating(false)
                setNewName('')
              }}
              className="shrink-0 rounded border border-panel-border px-2 py-1 text-xs text-panel-muted transition hover:text-gray-100"
            >
              {t('modal.close')}
            </button>
          </form>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <button
              onClick={() => setCreating(true)}
              disabled={busy}
              className="rounded border border-panel-border px-2 py-1 text-xs text-panel-muted transition hover:border-panel-accent hover:text-gray-100 disabled:opacity-40"
            >
              + {t('upload.new_folder')}
            </button>
            <button
              onClick={() => onPick(cur)}
              disabled={busy || !cur}
              className="rounded bg-panel-accent px-3 py-1 text-xs font-medium text-white transition disabled:opacity-40"
            >
              {t('upload.save_here')}
            </button>
          </div>
        )}
      </div>
    </Modal>
  )
}


// Iconos de chevron (estilo lucide): colapsar / expandir el panel.
function ChevronLeftIcon() {
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
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}

function ChevronRightIcon() {
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
      <polyline points="9 18 15 12 9 6" />
    </svg>
  )
}

function RefreshIcon() {
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
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <polyline points="21 3 21 9 15 9" />
    </svg>
  )
}

function PlusIcon() {
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
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
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

// Icono de carpeta (estilo lucide "folder"): navegador de carpetas.
function FolderIcon() {
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

// Icono de lápiz (estilo lucide "pencil"): renombrar.
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
      <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </svg>
  )
}

// Icono de check (estilo lucide "check"): confirmar renombrado.
function CheckIcon() {
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
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

// Icono de play (estilo lucide "play"): lanzar comando/proyecto.
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

// Icono de "abrir en pestaña nueva" (estilo lucide "external-link"): lanzar
// el proyecto en su propio espacio y mostrarlo en otra pestaña.
function ExternalLinkIcon() {
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
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
  )
}

// Icono de papelera (estilo lucide "trash-2").
function TrashIcon() {
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
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  )
}

// Icono de puerta abierta (estilo lucide "door-open"): terminar sesión.
// Mismo ícono que la cabecera de cada tile (TerminalTile).
function DoorIcon() {
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
      <path d="M13 4h3a2 2 0 0 1 2 2v14" />
      <path d="M2 20h3" />
      <path d="M13 20h9" />
      <path d="M10 12v.01" />
      <path d="M13 4.562v16.157a1 1 0 0 1-1.242.97L5 20V5.562a2 2 0 0 1 1.515-1.94l4-1A2 2 0 0 1 13 4.561Z" />
    </svg>
  )
}