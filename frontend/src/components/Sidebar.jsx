import React, { useEffect, useId, useRef, useState } from 'react'
import { ApiError, api } from '../api.js'
import { LANGUAGES, useT } from '../i18n/index.jsx'
import { CloseIcon, Modal } from './sidebar/Modal.jsx'
import { CommandSelect } from './sidebar/CommandSelect.jsx'
import { PasteForClaude } from './sidebar/PasteForClaude.jsx'
import { UploadFiles } from './sidebar/UploadFiles.jsx'
import { SectionCaret } from './sidebar/SectionCaret.jsx'
import { UNASSIGNED, spaceKeyOf } from '../spaces.js'
import logo from '../assets/logo.png'
import {
  ChartIcon,
  CheckIcon,
  ClockIcon,
  PencilIcon,
  PlusIcon,
  SpaceIcon,
  TrashIcon,
} from './sidebar/icons.jsx'
import { SpacesBar } from './sidebar/SpacesBar.jsx'
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
export function suggestName(existing) {
  const taken = new Set(existing)
  let n = 1
  while (taken.has(`sesion-${n}`)) n += 1
  return `sesion-${n}`
}

// Panel de Control (20%): catálogo de sesiones disponibles. Al hacer
// clic sobre una sesión se solicita su apertura en el grid.
export default function Sidebar({
  // Estado del reloj de trabajo (ver useWorkClock.js): si se está contando,
  // si está forzado a mano y cómo alternarlo.
  workClock,
  collapsed,
  onToggleCollapse,
  width,
  sessions,
  commands,
  projects,
  openNames,
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
  // Prefijo de los `id` que atan cada `<label>` con su campo. Sale de
  // `useId()` y no de cadenas escritas a mano —"nombre-sesion" a secas—
  // porque React garantiza que es único POR INSTANCIA: los identificadores no
  // chocarían aunque algún día el panel montara dos sidebars, y no hay que ir
  // comprobando a mano que ninguno se repite entre los cinco formularios.
  const uid = useId()
  // El espacio activo acota TODO el panel, no solo el grid: la lista de
  // sesiones muestra las de ese espacio.
  const spaceSessions = sessions.filter((s) => spaceKeyOf(s) === activeSpace)

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
  // Enlaces del proyecto: [{ url, title }]. Se editan aquí y se ven como
  // badges en la cabecera de la terminal que lanza el proyecto.
  const [projLinks, setProjLinks] = useState([])
  // Espacio al que irán las sesiones del proyecto. En el ALTA, '' no
  // significa "ninguno" sino "créame uno con el nombre del proyecto": es lo
  // que hace el backend y lo que anuncia el texto de debajo del selector.
  const [projSpace, setProjSpace] = useState('')
  const [projError, setProjError] = useState(null)
  const [projSubmitting, setProjSubmitting] = useState(false)

  // Edición en línea de un Proyecto.
  const [projEditingId, setProjEditingId] = useState(null)
  const [projEditTitle, setProjEditTitle] = useState('')
  const [projEditCwd, setProjEditCwd] = useState('')
  const [projEditCommands, setProjEditCommands] = useState([''])
  const [projEditLinks, setProjEditLinks] = useState([])
  // Aquí sí: '' es "ninguno". Editar no inventa espacios.
  const [projEditSpace, setProjEditSpace] = useState('')
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
      localStorage.setItem(HEIGHTS_KEY, JSON.stringify({ p: projectsH, c: commandsH }))
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
  const toggleSection = (name) => setOpenSection((cur) => (cur === name ? null : name))
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
      const cmd = cmdLine ? { command: cmdLine, cwd: cwd.trim() || null } : null
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
    setProjLinks([])
    setProjSpace('')
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
      await onSaveProject(
        title,
        projCwd.trim() || null,
        cmds,
        cleanLinks(projLinks),
        projSpace || null,
      )
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
    setProjEditLinks((p.links || []).map((l) => ({ ...l })))
    setProjEditSpace(p.space || '')
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
      await onUpdateProject(
        id,
        title,
        projEditCwd.trim() || null,
        cmds,
        cleanLinks(projEditLinks),
        projEditSpace || null,
      )
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
        {/* El cronómetro tiene que verse SIEMPRE, colapsado incluido: es el
            indicador de si se está registrando el tiempo, y un indicador que
            hay que desplegar para consultar no avisa de nada. */}
        <button
          onClick={workClock?.alternarManual}
          title={
            !workClock?.activo
              ? t('clock.idle')
              : workClock?.manual
                ? t('clock.manual')
                : t('clock.counting')
          }
          aria-label={t('clock.aria')}
          aria-pressed={Boolean(workClock?.manual)}
          className={`mt-2 rounded p-1.5 transition hover:bg-panel-bg ${
            !workClock?.activo
              ? 'text-panel-muted hover:text-gray-100'
              : workClock?.manual
                ? 'text-amber-400'
                : 'text-green-400'
          }`}
        >
          <ClockIcon activo={Boolean(workClock?.activo)} />
        </button>
        <a
          href="/dashboard"
          target="_blank"
          rel="noopener noreferrer"
          title={t('dashboard.title')}
          aria-label={t('dashboard.title')}
          className="mt-2 rounded p-1.5 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
        >
          <ChartIcon />
        </a>
      </aside>
    )
  }

  return (
    <aside
      style={{ width }}
      className="flex h-full shrink-0 flex-col border-r border-panel-border bg-panel-surface text-gray-100"
    >
      {/* Dos filas FIJAS y no un `flex-wrap` con el título dentro: con el
          ancho mínimo del sidebar (220 px) los iconos no caben junto al
          nombre, y dejándolo al azar del wrap la cabecera salía en tres
          líneas con el título encajado en medio. Arriba el nombre y el
          plegado —lo que siempre tiene que estar a mano—, abajo las
          acciones. */}
      <header className="border-b border-panel-border bg-black px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          {/* El logo ES el nombre: lleva las siglas dentro. El `alt` mantiene
              el nombre para quien no ve la imagen (lector de pantalla, o el
              PNG que no carga), y el `h1` sigue ahí porque el encabezado de
              la página no puede depender de que una imagen cargue. */}
          <h1 className="flex min-w-0 items-center">
            <img
              src={logo}
              alt={t('app.brand')}
              width="26"
              height="26"
              className="shrink-0"
            />
          </h1>
          <button
            onClick={onToggleCollapse}
            title={t('sidebar.collapse')}
            className="shrink-0 rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <ChevronLeftIcon />
          </button>
        </div>
        {/* `flex-wrap` de todos modos: si el usuario baja el sidebar al
            mínimo con un idioma de nombres largos, es preferible una tercera
            línea a un botón fuera de la barra que no se puede pulsar — lo
            cazaron los E2E al añadir el cronómetro. */}
        <div className="mt-1 flex flex-wrap items-center justify-end gap-0.5">
          {LAYOUTS.map((mode) => (
            <button
              key={mode}
              onClick={() => onSetLayout(mode)}
              title={t(`grid.layout_${mode}`)}
              aria-label={t(`grid.layout_${mode}`)}
              aria-pressed={layout === mode}
              className={`rounded p-1 transition hover:bg-panel-bg ${
                layout === mode
                  ? 'text-panel-accent'
                  : 'text-panel-muted hover:text-gray-100'
              }`}
            >
              <LayoutIcon mode={mode} />
            </button>
          ))}
          <span className="mx-0.5 h-4 w-px bg-panel-border" />
          {/* Cronómetro: verde cuando el tiempo se está contando, apagado
              cuando no. Es el mando de "no me fío": si el detector no ve la
              actividad (leer un rato largo sin tocar nada), se pulsa y cuenta
              igual — con caducidad, para que un olvido no apunte la noche. */}
          <button
            onClick={workClock?.alternarManual}
            title={
              !workClock?.activo
                ? t('clock.idle')
                : workClock?.manual
                  ? t('clock.manual')
                  : t('clock.counting')
            }
            aria-label={t('clock.aria')}
            aria-pressed={Boolean(workClock?.manual)}
            // Ámbar y no verde en modo declarado: el color distingue "lo
            // estoy midiendo" de "me estás diciendo que trabajas", que es la
            // misma distinción que guarda la base y que separa el dashboard.
            className={`rounded p-1 transition hover:bg-panel-bg ${
              !workClock?.activo
                ? 'text-panel-muted hover:text-gray-100'
                : workClock?.manual
                  ? 'text-amber-400'
                  : 'text-green-400'
            }`}
          >
            <ClockIcon activo={Boolean(workClock?.activo)} />
          </button>
          <a
            href="/dashboard"
            target="_blank"
            rel="noopener noreferrer"
            title={t('dashboard.title')}
            aria-label={t('dashboard.title')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <ChartIcon />
          </a>
          <span className="mx-0.5 h-4 w-px bg-panel-border" />
          <button
            onClick={openForm}
            title={t('sidebar.new_session')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <PlusIcon />
          </button>
          <button
            onClick={onRefresh}
            title={t('sidebar.refresh')}
            className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
          >
            <RefreshIcon />
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
                        className="flex min-w-0 flex-1 items-center px-3 py-2 text-left"
                        title={isOpen ? t('sidebar.bring_to_front') : t('sidebar.open')}
                      >
                        {/* Punto de estado y nombre, y nada más. Aquí hubo un
                          «abierta» y un contador de ventanas de tmux, y los
                          dos se fueron por lo mismo: se comían el ancho del
                          nombre —que es lo único que de verdad distingue una
                          fila de otra— para decir algo que ya se ve en otro
                          sitio o que no se usa. Que la sesión está abierta lo
                          dicen el fondo de la fila, el nombre atenuado y la ✕
                          de ocultar, que solo existe si lo está. */}
                        <span className="flex items-center gap-2 truncate">
                          <span
                            className={`h-2 w-2 shrink-0 rounded-full ${
                              s.attached ? 'bg-green-400' : 'bg-panel-muted'
                            }`}
                            title={
                              s.attached ? t('sidebar.attached') : t('sidebar.detached')
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
                      </button>
                      {/* Los controles de hover COLAPSAN, no se limitan a
                        volverse transparentes: `opacity-0` sigue ocupando su
                        hueco, y esos ~110px se los quitaba al nombre de la
                        sesión en reposo, que es cuando de verdad quieres
                        leerlo. `focus-within` los saca también con el
                        teclado, que si no serían inalcanzables sin ratón.

                        Y donde NO hay hover —el móvil, y este panel se usa
                        desde el móvil— se quedan desplegados siempre: si no,
                        no habría forma de llegar a ellos con el dedo. */}
                      <div className="flex max-w-0 shrink-0 items-center overflow-hidden opacity-0 transition-all focus-within:max-w-[8rem] focus-within:opacity-100 group-hover:max-w-[8rem] group-hover:opacity-100 [@media(hover:none)]:max-w-[8rem] [@media(hover:none)]:opacity-100">
                        <MoveToSpace
                          session={s}
                          spaces={spaces}
                          onAssign={onAssignSpace}
                        />
                        <button
                          onClick={() => startRename(s)}
                          title={t('sidebar.rename_session')}
                          className="shrink-0 rounded p-1.5 text-panel-muted transition hover:bg-panel-surface hover:text-gray-100"
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
                      </div>
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
                        title={t('sidebar.run_in_new_session')}
                        className="shrink-0 rounded p-0.5 text-panel-muted transition hover:bg-panel-surface hover:text-green-400"
                      >
                        <PlayIcon />
                      </button>
                      <span
                        className="min-w-0 flex-1 truncate font-medium text-gray-100"
                        title={c.command}
                      >
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
                          title={[p.title, p.cwd, ...p.commands]
                            .filter(Boolean)
                            .join(' · ')}
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
        space={activeSpace}
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
            <label
              htmlFor={`${uid}-nombre-sesion`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.session_name_label')}
            </label>
            <input
              id={`${uid}-nombre-sesion`}
              autoFocus
              value={newName}
              onChange={(e) => setNewName(sanitizeSessionName(e.target.value))}
              onFocus={(e) => e.target.select()}
              className="w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mt-1 text-xs text-panel-muted">
              {t('form.session_name_hint')}
            </p>

            <label
              htmlFor={`${uid}-comando-arranque`}
              className="mb-1 mt-3 block text-xs uppercase tracking-wide text-panel-muted"
            >
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
              id={`${uid}-comando-arranque`}
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
            <label
              htmlFor={`${uid}-editar-etiqueta`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.name_optional_label')}
            </label>
            <input
              id={`${uid}-editar-etiqueta`}
              autoFocus
              value={editLabel}
              onChange={(e) => setEditLabel(e.target.value)}
              placeholder={t('form.name_optional_placeholder')}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <label
              htmlFor={`${uid}-editar-comando`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.command_label')}
            </label>
            <input
              id={`${uid}-editar-comando`}
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
        <Modal
          title={t('form.new_project_title')}
          onClose={closeProjForm}
          panelClassName="max-w-lg"
        >
          <form onSubmit={submitProjCreate}>
            <label
              htmlFor={`${uid}-proyecto-titulo`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.title_label')}
            </label>
            <input
              id={`${uid}-proyecto-titulo`}
              autoFocus
              value={projTitle}
              onChange={(e) => setProjTitle(sanitizeSessionName(e.target.value))}
              placeholder={t('form.project_title_placeholder')}
              className="mb-1 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-3 text-xs text-panel-muted">
              {t('form.project_title_hint')}
            </p>
            <label
              htmlFor={`${uid}-proyecto-dir`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.directory_label')}
            </label>
            <DirectoryInput
              id={`${uid}-proyecto-dir`}
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
              className="mb-3 block text-xs text-panel-muted transition hover:text-panel-accent"
            >
              {t('form.add_command')}
            </button>
            <LinksFields links={projLinks} onChange={setProjLinks} />
            <label
              htmlFor={`${uid}-proyecto-espacio`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.project_space_label')}
            </label>
            <select
              id={`${uid}-proyecto-espacio`}
              value={projSpace}
              onChange={(e) => setProjSpace(e.target.value)}
              className="mb-1 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            >
              <option value="">{t('form.project_space_new')}</option>
              {spaces.map((sp) => (
                <option key={sp.id} value={sp.id}>
                  {sp.title}
                </option>
              ))}
            </select>
            <p className="mb-3 text-xs text-panel-muted">
              {t('form.project_space_hint_new')}
            </p>
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
        <Modal
          title={t('form.edit_project_title')}
          onClose={cancelProjEdit}
          panelClassName="max-w-lg"
        >
          <form onSubmit={(e) => submitProjEdit(e, projEditingId)}>
            <label
              htmlFor={`${uid}-editar-proyecto-titulo`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.title_label')}
            </label>
            <input
              id={`${uid}-editar-proyecto-titulo`}
              autoFocus
              value={projEditTitle}
              onChange={(e) => setProjEditTitle(sanitizeSessionName(e.target.value))}
              placeholder={t('form.title_placeholder')}
              className="mb-1 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            />
            <p className="mb-3 text-xs text-panel-muted">
              {t('form.project_title_hint')}
            </p>
            <label
              htmlFor={`${uid}-editar-proyecto-dir`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.directory_label')}
            </label>
            <DirectoryInput
              id={`${uid}-editar-proyecto-dir`}
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
              className="mb-3 block text-xs text-panel-muted transition hover:text-panel-accent"
            >
              {t('form.add_command')}
            </button>
            <LinksFields links={projEditLinks} onChange={setProjEditLinks} />
            <label
              htmlFor={`${uid}-editar-proyecto-espacio`}
              className="mb-1 block text-xs uppercase tracking-wide text-panel-muted"
            >
              {t('form.project_space_label')}
            </label>
            <select
              id={`${uid}-editar-proyecto-espacio`}
              value={projEditSpace}
              onChange={(e) => setProjEditSpace(e.target.value)}
              className="mb-3 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
            >
              <option value="">{t('form.project_space_none')}</option>
              {spaces.map((sp) => (
                <option key={sp.id} value={sp.id}>
                  {sp.title}
                </option>
              ))}
            </select>
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

// Mueve una sesión a otro espacio. Sigue siendo un <select> NATIVO —es lo
// que mejor funciona con el dedo, y este panel se usa también desde el
// móvil—, pero se dibuja como un icono: el desplegable va encima,
// transparente, cubriendo el icono. Así el control ocupa lo que un botón en
// vez de los ~7rem que le comía al nombre de la sesión, y aun así el que se
// abre al pulsarlo es el selector del sistema, con su teclado y su
// accesibilidad ya resueltos.
//
// El nombre del espacio ya no se lee aquí, y no hace falta: la vista «Todas»
// se retiró (ver `spaces.js`), así que todas las sesiones de la lista son del
// espacio que está elegido arriba.
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
    <span
      title={error || t('spaces.move')}
      className={`relative mr-1 shrink-0 rounded p-1.5 transition hover:bg-panel-surface ${
        error ? 'text-red-400' : 'text-panel-muted hover:text-gray-100'
      }`}
    >
      <SpaceIcon />
      <select
        value={value}
        onChange={change}
        aria-label={t('spaces.move')}
        className="absolute inset-0 cursor-pointer opacity-0 outline-none"
      >
        <option value={UNASSIGNED}>{t('spaces.unassigned')}</option>
        {spaces.map((s) => (
          <option key={s.id} value={s.id}>
            {s.title}
          </option>
        ))}
      </select>
    </span>
  )
}

// Deja solo los enlaces con URL. Un título sin URL no es un enlace, y una
// fila vacía es lo normal mientras se edita: filtrar aquí evita que el
// backend rechace el proyecto entero por una fila a medio escribir.
function cleanLinks(links) {
  return links
    .map((l) => ({ url: (l.url || '').trim(), title: (l.title || '').trim() }))
    .filter((l) => l.url)
}

// Editor de los enlaces de un proyecto: una fila por enlace con la URL y el
// texto de la badge. El título es opcional a propósito —el backend cae al
// host de la URL—, así que pegar una URL y darle a guardar ya vale.
function LinksFields({ links, onChange }) {
  const { t } = useT()
  const setAt = (i, patch) =>
    onChange(links.map((l, idx) => (idx === i ? { ...l, ...patch } : l)))

  return (
    <>
      <p className="mb-1 text-xs uppercase tracking-wide text-panel-muted">
        {t('form.links_label')}
      </p>
      {links.map((link, i) => (
        <div key={i} className="mb-1 flex items-center gap-1">
          <input
            value={link.url || ''}
            onChange={(e) => setAt(i, { url: e.target.value })}
            placeholder={t('form.link_url_placeholder')}
            aria-label={t('form.link_url_placeholder')}
            className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
          />
          <input
            value={link.title || ''}
            onChange={(e) => setAt(i, { title: e.target.value })}
            placeholder={t('form.link_title_placeholder')}
            aria-label={t('form.link_title_placeholder')}
            className="w-28 shrink-0 rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
          />
          <button
            type="button"
            onClick={() => onChange(links.filter((_, idx) => idx !== i))}
            title={t('form.remove')}
            className="shrink-0 rounded p-0.5 text-panel-muted transition hover:text-red-400"
          >
            <CloseIcon />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...links, { url: '', title: '' }])}
        className="mb-3 block text-xs text-panel-muted transition hover:text-panel-accent"
      >
        {t('form.add_link')}
      </button>
    </>
  )
}

function DirectoryInput({ id, value, onChange, placeholder, className }) {
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
        id={id}
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
      setError(err instanceof ApiError ? tError(err) : t('form.save_command_failed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={submit}>
      {/* `aria-label` y no un `<label>` visible: este formulario es
          deliberadamente compacto —dos campos y un botón dentro de un modal
          pequeño— y meterle dos etiquetas encima cambiaría el diseño. Lo que
          NO puede quedarse es un campo sin nombre: un `placeholder` no sirve
          de nombre accesible, porque desaparece en cuanto se escribe y los
          lectores de pantalla no lo tratan igual. */}
      <input
        autoFocus
        aria-label={t('form.name_optional_label')}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={t('form.name_optional_placeholder')}
        className="mb-2 w-full rounded border border-panel-border bg-panel-bg px-2 py-1.5 text-sm outline-none focus:border-panel-accent"
      />
      <input
        aria-label={t('form.command_label')}
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

// Icono de carpeta (estilo lucide "folder"): navegador de carpetas.

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
