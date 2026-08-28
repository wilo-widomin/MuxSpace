import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Sidebar, { Resizer } from './components/Sidebar.jsx'
import SessionGrid, { LAYOUTS } from './components/SessionGrid.jsx'
import LoginScreen from './components/LoginScreen.jsx'
import { api, ApiError } from './api.js'
import { initialSpace, UNASSIGNED } from './spaces.js'
import { porNombre } from './lib/orden.js'
import { useWorkClock } from './useWorkClock.js'
import { useWorkPause } from './useWorkPause.js'
import PauseQuestion from './components/PauseQuestion.jsx'
import Dashboard from './components/Dashboard.jsx'
import { useT } from './i18n/index.jsx'

// ---- Espacios y visibilidad ----
// Un **espacio** agrupa sesiones (un cliente, una categoría). Cada sesión
// pertenece como mucho a uno; las que no, caen en el espacio virtual
// "Sin asignar". El pseudo-espacio "Todas" muestra el conjunto entero.
//
// El reparto de estado es deliberado, y es lo que permite tener dos
// pestañas con vistas distintas:
//
//   - QUÉ espacios existen y de quién es cada sesión -> servidor
//     (`spaces.json`), porque es organización duradera y compartida entre
//     dispositivos.
//   - QUÉ espacio mira ESTA pestaña -> sessionStorage, propio de la
//     pestaña. Antes esto vivía en un registro global del backend
//     (`open_registry`), así que abrir una terminal en una pestaña la
//     hacía aparecer en la otra al siguiente sondeo.
//   - QUÉ tiles ocultó el usuario -> localStorage, para que ocultar una
//     ventana sobreviva a recargar la página.
const ACTIVE_SPACE_KEY = 'muxspace:active-space'
const HIDDEN_KEY = 'muxspace:hidden-sessions'
const ORDER_KEY = 'muxspace:session-order'
const LAYOUT_KEY = 'muxspace:grid-layout'

// Lectura tolerante: si el almacenamiento no está disponible (modo privado)
// o el valor está corrupto, se sigue con el valor por defecto.
function readJSON(storage, key, fallback) {
  try {
    const raw = storage.getItem(key)
    if (!raw) return fallback
    const value = JSON.parse(raw)
    return Array.isArray(value) ? value : fallback
  } catch {
    return fallback
  }
}

function writeJSON(storage, key, value) {
  try {
    storage.setItem(key, JSON.stringify(value))
  } catch {
    /* sin almacenamiento: la preferencia solo dura lo que la pestaña */
  }
}

export default function App() {
  const { t, tError } = useT()
  const [authed, setAuthed] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)
  const [loginError, setLoginError] = useState(null)

  const [sessions, setSessions] = useState([])
  const [commands, setCommands] = useState([])
  const [projects, setProjects] = useState([])
  const [spaces, setSpaces] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Espacio que mira esta pestaña. En sessionStorage: cada pestaña elige el
  // suyo y lo recuerda al recargar, pero no se lo impone a las demás.
  // «Todas» ya no se ofrece en el selector, así que un valor guardado de una
  // sesión anterior se degrada a «Sin asignar».
  // `?space=<id>` manda sobre lo guardado: es como llega una pestaña abierta
  // desde el botón "abrir proyecto en pestaña nueva", que necesita fijar el
  // espacio de destino aunque esta pestaña sea reutilizada por el navegador.
  // `/dashboard` es una vista alternativa de la MISMA aplicación (el backend
  // sirve ahí el mismo index.html). Se decide una vez: no hay navegación
  // dentro de la pestaña, se abre en una nueva.
  const esDashboard = window.location.pathname === '/dashboard'

  const [activeSpace, setActiveSpace] = useState(() =>
    initialSpace(window.location.search, sessionStorage.getItem(ACTIVE_SPACE_KEY)),
  )

  // El `?space=` se consume UNA vez y se quita de la URL. Es una orden de
  // apertura, no el estado de la pestaña: mientras siguiera ahí, cada recarga
  // volvía a imponerlo y te sacaba del espacio en el que estabas trabajando,
  // sin avisar y sin que nada en pantalla explicara por qué.
  useEffect(() => {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('space')) return
    url.searchParams.delete('space')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }, [])

  useEffect(() => {
    try {
      sessionStorage.setItem(ACTIVE_SPACE_KEY, activeSpace)
    } catch {
      /* sin sessionStorage: se pierde al recargar, nada más */
    }
  }, [activeSpace])

  // Sesiones que el usuario ocultó del grid. La sesión de tmux sigue viva y
  // sigue en el sidebar; simplemente no se renderiza su terminal.
  const [hidden, setHidden] = useState(
    () => new Set(readJSON(localStorage, HIDDEN_KEY, [])),
  )
  const hideSession = useCallback((name) => {
    setHidden((prev) => {
      const next = new Set(prev)
      next.add(name)
      writeJSON(localStorage, HIDDEN_KEY, [...next])
      return next
    })
  }, [])
  const unhideSession = useCallback((name) => {
    setHidden((prev) => {
      if (!prev.has(name)) return prev
      const next = new Set(prev)
      next.delete(name)
      writeJSON(localStorage, HIDDEN_KEY, [...next])
      return next
    })
  }, [])

  // Orden manual de los tiles (drag & drop). Es una única lista global de
  // nombres: como cada sesión está en un solo espacio, filtrarla por espacio
  // da el orden de ese espacio sin necesidad de una lista por espacio.
  const [order, setOrder] = useState(() => readJSON(localStorage, ORDER_KEY, []))
  const persistOrder = useCallback((next) => {
    writeJSON(localStorage, ORDER_KEY, next)
    return next
  }, [])

  // Disposición de las terminales: 'auto' (rejilla), 'cols' (una al lado de
  // otra) o 'rows' (una encima de otra). Vive aquí porque los botones están
  // en la cabecera del sidebar y el grid es quien la aplica.
  const [layout, setLayout] = useState(() => {
    const saved = readJSON(localStorage, LAYOUT_KEY, 'auto')
    return LAYOUTS.includes(saved) ? saved : 'auto'
  })
  const changeLayout = useCallback((next) => {
    setLayout(next)
    writeJSON(localStorage, LAYOUT_KEY, next)
  }, [])

  // Terminal maximizada (modo foco), o null para la disposición normal. No se
  // persiste: es un estado del momento, no una preferencia. Si esa sesión se
  // cierra, el grid vuelve solo a la disposición normal.
  const [focusedName, setFocusedName] = useState(null)

  // Terminales minimizadas: siguen abiertas y conectadas, pero fuera de la
  // rejilla (se ven como una pestaña en la barra de arriba). Tampoco se
  // persiste, por el mismo motivo que el modo foco. Minimizar la que está
  // maximizada sale del modo foco: si no, quedaría maximizada y escondida.
  const [minimizedNames, setMinimizedNames] = useState(() => new Set())
  const toggleMinimized = useCallback((name) => {
    setFocusedName((f) => (f === name ? null : f))
    setMinimizedNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])
  const restoreAllMinimized = useCallback(() => setMinimizedNames(new Set()), [])

  // Nombre de la sesión/tile con foco (la última clicada). Destino de los
  // comandos ejecutados desde el sidebar. null => "abrir en sesión nueva".
  const [activeName, setActiveName] = useState(null)

  // Petición de foco de teclado para UNA terminal concreta: cada vez que se
  // abre un proyecto/comando desde el panel, apuntamos a su sesión y subimos
  // el `token`; la terminal correspondiente toma el foco al ver el cambio.
  // Así se puede escribir en la terminal recién abierta sin hacer clic, y no
  // se roba el foco al cambiar de pestaña.
  const [focusReq, setFocusReq] = useState({ name: null, token: 0 })
  const focusTerminal = (name) => setFocusReq((r) => ({ name, token: r.token + 1 }))

  // Colapsar/expandir el sidebar para ganar espacio en el grid. Persiste
  // la preferencia en localStorage para que sobreviva a recargas.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('sidebarCollapsed') === '1',
  )
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((c) => {
      const next = !c
      localStorage.setItem('sidebarCollapsed', next ? '1' : '0')
      return next
    })
  }, [])

  // Ancho del sidebar arrastrable (divisor vertical en su borde derecho).
  // Persiste el valor en localStorage para que sobreviva a recargas.
  const clampSidebarWidth = (w) => {
    const maxByWin = (typeof window !== 'undefined' ? window.innerWidth : 1280) - 420
    return Math.max(220, Math.min(w, Math.min(760, Math.max(220, maxByWin))))
  }
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = Number(localStorage.getItem('muxspace-sidebar-width'))
    return Number.isFinite(stored) && stored > 0
      ? clampSidebarWidth(stored)
      : clampSidebarWidth(300)
  })
  const resizeSidebar = useCallback((dx) => {
    setSidebarWidth((w) => clampSidebarWidth(w + dx))
  }, [])
  useEffect(() => {
    localStorage.setItem('muxspace-sidebar-width', String(sidebarWidth))
  }, [sidebarWidth])

  // Sesiones del espacio activo que no están ocultas: exactamente lo que
  // se renderiza en el grid. Es un valor DERIVADO, no un estado propio; por
  // eso el sondeo periódico ya no puede reañadir nada a la vista.
  const openSessions = useMemo(() => {
    const inSpace = sessions.filter((s) =>
      activeSpace === UNASSIGNED ? !s.space : s.space === activeSpace,
    )
    const visible = inSpace.filter((s) => !hidden.has(s.name))
    // Orden manual primero; las que no aparecen en él (sesiones nuevas) van
    // al final, alfabéticamente, en vez de en un orden arbitrario.
    const rank = new Map(order.map((name, i) => [name, i]))
    return (
      visible
        .slice()
        .sort((a, b) => {
          const ra = rank.has(a.name) ? rank.get(a.name) : Infinity
          const rb = rank.has(b.name) ? rank.get(b.name) : Infinity
          if (ra !== rb) return ra - rb
          return a.name.localeCompare(b.name)
        })
        // Se recorta a lo que el grid necesita, y `project` es parte de eso:
        // es lo que le dice a la cabecera de cada terminal qué enlaces del
        // proyecto tiene que pintar. Cuando aquí solo iba el nombre, las badges
        // no aparecían nunca y el tile no tenía forma de saber por qué.
        .map((s) => ({ name: s.name, project: s.project ?? null }))
    )
  }, [sessions, activeSpace, hidden, order])

  // ---- Sesión caducada ----
  // Memoizada y con `t` en las dependencias: la usan los tres cargadores de
  // abajo, y si fuera una función nueva en cada render los invalidaría a
  // todos continuamente. Va aquí arriba, antes que ellos, por lo mismo que
  // explica el comentario del bloque siguiente.
  const handleAuthFailure = useCallback(() => {
    setAuthed(false)
    setLoginError(t('app.session_expired'))
  }, [t])

  // ---- Carga de los espacios ----
  // Declarado junto al resto de cargadores y ANTES del efecto que los
  // dispara: un `const` referenciado en el array de dependencias de un
  // useEffect se evalúa en cada render, así que declararlo más abajo
  // reventaba con un ReferenceError de zona muerta temporal.
  const loadSpaces = useCallback(async () => {
    try {
      setSpaces(await api.listSpaces())
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleAuthFailure()
      // Sin espacios seguimos funcionando: todo cae en "Sin asignar".
    }
  }, [handleAuthFailure])

  // ---- Carga de la biblioteca (comandos + proyectos) ----
  // Se cargan de forma independiente: si uno falla (p. ej. el backend
  // aún no expone /api/projects tras una actualización), el otro sigue
  // visible en vez de caer ambos.
  const loadCommands = useCallback(async () => {
    const tasks = [
      { key: 'commands', fn: () => api.listCommands(), set: setCommands },
      { key: 'projects', fn: () => api.listProjects(), set: setProjects },
    ]
    await Promise.all(
      tasks.map(async (t) => {
        try {
          t.set(await t.fn())
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            handleAuthFailure()
          }
          // Error no fatal: dejamos la otra mitad de la biblioteca intacta.
        }
      }),
    )
  }, [handleAuthFailure])

  // Evita apilar sondeos: si la petición anterior de /api/sessions sigue
  // en vuelo (red lenta, diálogo de certificado mTLS, backend caído), el
  // siguiente tick del intervalo no lanza otra idéntica encima.
  const sessionsInFlightRef = useRef(false)

  // ---- Carga de sesiones desde el backend ----
  // `background` true => encuesta periódica en segundo plano: no togglear
  // `loading` para que el sidebar no parpadee con el "Cargando…" cada 8 s.
  // Los sondeos de fondo se descartan si hay otra petición pendiente o la
  // pestaña está oculta; las cargas manuales (acciones del usuario) siempre
  // se ejecutan.
  const loadSessions = useCallback(
    async (background = false) => {
      if (background && (sessionsInFlightRef.current || document.hidden)) return
      sessionsInFlightRef.current = true
      if (!background) setLoading(true)
      setError(null)
      try {
        // El sondeo solo refresca el catálogo. Qué se ve en el grid se deriva
        // de aquí más el espacio activo y las ocultas (ambos, del cliente):
        // ninguna respuesta del servidor puede reabrir una ventana.
        const data = await api.listSessions()
        setSessions(data)
        // Una sesión que ya no existe deja de estar oculta: si más adelante
        // se crea otra con el mismo nombre, debe aparecer.
        setHidden((prev) => {
          const alive = new Set(data.map((s) => s.name))
          const next = new Set([...prev].filter((name) => alive.has(name)))
          if (next.size === prev.size) return prev
          writeJSON(localStorage, HIDDEN_KEY, [...next])
          return next
        })
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          handleAuthFailure()
        } else {
          setError(tError(err))
        }
      } finally {
        sessionsInFlightRef.current = false
        if (!background) setLoading(false)
      }
    },
    [handleAuthFailure, tError],
  )

  // Todo lo que se lista va ordenado alfabéticamente (ver `porNombre`).
  const commandsOrdenados = useMemo(() => porNombre(commands, 'label'), [commands])
  const projectsOrdenados = useMemo(() => porNombre(projects, 'title'), [projects])
  const spacesOrdenados = useMemo(() => porNombre(spaces, 'title'), [spaces])

  // Reloj de trabajo: late al servidor mientras HAYA entrada del usuario y
  // esta pestaña tenga el foco. Cuenta al espacio que se está mirando y anota
  // qué sesión estaba activa, para poder separar después las horas con un
  // agente delante. La salida del terminal no cuenta (ver `worklog.js`).
  // En la vista de tiempos no se cuenta: mirar cuánto has trabajado no es
  // trabajar en un proyecto, y contarlo ahí ensuciaría el espacio activo.
  const workClock = useWorkClock(activeSpace, activeName, authed && !esDashboard)
  // Las pausas van aparte del reloj: el reloj mide dónde estás, la pausa dice
  // que no estás en ninguna parte. En la vista de tiempos también valen —irse
  // a comer se marca igual desde el dashboard.
  const workPause = useWorkPause(authed)

  // Si la tile con foco desaparece del grid (cierre/kill), liberamos el foco.
  useEffect(() => {
    if (activeName && !openSessions.some((s) => s.name === activeName)) {
      setActiveName(null)
    }
  }, [openSessions, activeName])

  // ---- Comprobación inicial de autenticación ----
  // Si hay una cookie de sesión válida (de un login anterior), /api/me
  // responde 200 y entramos directos; si no, se muestra el login.
  useEffect(() => {
    api
      .me()
      .then(() => setAuthed(true))
      .catch(() => {})
      .finally(() => setAuthChecked(true))
  }, [])

  // ---- Carga periódica una vez autenticado ----
  useEffect(() => {
    if (!authed) return
    loadSessions()
    loadCommands()
    loadSpaces()
    const interval = setInterval(() => loadSessions(true), 8000)
    return () => clearInterval(interval)
    // Los tres cargadores dependen ahora de `t`/`tError`, así que cambiar de
    // idioma los invalida y este efecto se rehace: una recarga extra y un
    // intervalo nuevo. Es un precio aceptable —cambiar de idioma es un acto
    // deliberado y poco frecuente— y a cambio los mensajes de error salen en
    // el idioma que el usuario está viendo.
  }, [authed, loadSessions, loadCommands, loadSpaces])

  // ---- Título de la pestaña ----
  // Lleva el nombre del espacio porque cada pestaña mira uno, y con varias
  // abiertas el título es lo ÚNICO que las distingue: sin él, todas ponían
  // «MuxSpace» y había que entrar en cada una para saber cuál era cuál.
  //
  // Sin autenticar se queda el nombre a secas: los espacios son datos del
  // usuario y no tienen por qué leerse en la barra del navegador de una
  // pantalla de login. Es también lo que se ve mientras cargan.
  useEffect(() => {
    const espacio =
      activeSpace === UNASSIGNED
        ? t('spaces.unassigned')
        : spaces.find((s) => s.id === activeSpace)?.title
    document.title =
      authed && espacio ? t('app.title_space', { space: espacio }) : t('app.title')
  }, [authed, activeSpace, spaces, t])

  // ---- Login ----
  // El backend valida y deja la sesión en una cookie HttpOnly; aquí no se
  // retiene la contraseña en ningún momento.
  const handleLogin = async (username, password) => {
    setLoginError(null)
    try {
      await api.login(username, password)
      setAuthed(true)
    } catch (err) {
      // Un fallo de red no llega como ApiError: su `message` lo redacta el
      // navegador en SU idioma, así que ahí ponemos texto propio.
      setLoginError(err instanceof ApiError ? tError(err) : t('app.server_unreachable'))
    }
  }

  const handleLogout = async () => {
    try {
      await api.logout()
    } catch {
      // Aunque el logout falle (p. ej. sin red), cerramos la vista local.
    }
    setSessions([])
    setSpaces([])
    setActiveName(null)
    setAuthed(false)
    setLoginError(null)
  }

  // ---- Crear una nueva sesión de tmux desde el sidebar ----
  // Crea la sesión (opcionalmente con un comando de la biblioteca),
  // refresca el listado y la abre en el grid. Propaga el error (p. ej.
  // nombre duplicado/invalido) para que el sidebar lo muestre sin cerrar
  // el formulario.
  const handleCreateSession = async (name, command) => {
    // `command` (opcional) viene del form de nueva sesión del sidebar y
    // puede llevar un comando de arranque y un directorio inicial propios.
    const body = command ? { command: command.command, cwd: command.cwd } : {}
    await api.createSession(name, body)
    // Crear estando dentro de un espacio mete ahí la sesión: si no, la
    // recién creada aparecería en "Sin asignar" y no en el grid que miras.
    await assignToActiveSpace(name)
    await loadSessions()
    await handleSelect(name)
  }

  // ---- Otra terminal en el mismo directorio (icono del tile) ----
  // El directorio no se calcula aquí: el backend lo lee del panel de tmux de
  // la sesión de origen y devuelve el nombre que le tocó a la nueva
  // ("Terminal", "Terminal (2)"…). Lo demás es lo mismo que crear una
  // sesión desde el sidebar: al espacio activo, refrescar y abrirla.
  const handleSpawnTerminal = async (name) => {
    try {
      const { name: nueva } = await api.spawnTerminal(name)
      await assignToActiveSpace(nueva)
      await loadSessions()
      await handleSelect(nueva)
    } catch (err) {
      setError(tError(err))
    }
  }

  // Asigna una sesión recién creada al espacio que mira esta pestaña. En
  // "Sin asignar" no hay a dónde asignar, así que se queda suelta.
  const assignToActiveSpace = async (name) => {
    if (activeSpace === UNASSIGNED) return
    try {
      await api.assignSessionSpace(name, activeSpace)
    } catch {
      // Que falle la asignación no debe abortar la creación de la sesión:
      // la terminal ya existe y aparecerá en "Sin asignar".
    }
  }

  // ---- Renombrar una sesión existente ----
  // Renombra en tmux y refresca el listado. El tile del grid NO hay que
  // tocarlo: `openSessions` es un valor derivado de `sessions`, así que se
  // recalcula solo con el nombre nuevo. Lo que sí hay que arrastrar a mano
  // es el estado de cliente que guarda el nombre viejo como clave —foco,
  // orden manual y ocultas—, o la sesión perdería su sitio en el grid.
  const handleRenameSession = async (oldName, newName) => {
    await api.renameSession(oldName, newName)
    setActiveName((current) => (current === oldName ? newName : current))
    setOrder((current) =>
      current.includes(oldName)
        ? persistOrder(current.map((n) => (n === oldName ? newName : n)))
        : current,
    )
    // Sin esto, `loadSessions` daría el nombre viejo por muerto, lo quitaría
    // de `hidden` y la ventana que el usuario había cerrado reaparecería.
    setHidden((prev) => {
      if (!prev.has(oldName)) return prev
      const next = new Set(prev)
      next.delete(oldName)
      next.add(newName)
      writeJSON(localStorage, HIDDEN_KEY, [...next])
      return next
    })
    await loadSessions()
  }

  // ---- Lanzar un comando de la biblioteca como nueva sesión ----
  // El backend elige el nombre (el del comando, con sufijo incremental si
  // ya existe). Refrescamos y abrimos la nueva sesión en el grid.
  const handleLaunchCommand = async (id) => {
    const res = await api.launchCommand(id)
    await assignToActiveSpace(res.name)
    await loadSessions()
    await handleSelect(res.name)
    return res.name
  }

  // ---- Guardar un comando nuevo en la biblioteca ----
  // Devuelve el comando creado para que el sidebar pueda seleccionarlo.
  const handleSaveCommand = async (label, command) => {
    const created = await api.createCommand(label, command)
    await loadCommands()
    return created
  }

  // ---- Editar un comando existente de la biblioteca ----
  // Actualiza label/comando y refresca el listado.
  const handleUpdateCommand = async (id, label, command) => {
    const updated = await api.updateCommand(id, label, command)
    await loadCommands()
    return updated
  }

  // ---- Eliminar un comando de la biblioteca ----
  const handleDeleteCommand = async (id) => {
    await api.deleteCommand(id)
    await loadCommands()
  }

  // ---- Ejecutar un Comando (una línea) ----
  // Siempre en una ventana nueva: el comando nunca se cuela en la terminal
  // que el usuario tenía delante (podía estar a media faena). Si hay foco,
  // se lo lleva la ventana recién abierta.
  const handleRunCommand = async (cmd) => {
    try {
      const name = await handleLaunchCommand(cmd.id)
      if (name) focusTerminal(name)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) handleAuthFailure()
      else setError(tError(err))
    }
  }

  // ---- Guardar / editar / eliminar un Proyecto ----
  const handleSaveProject = async (title, cwd, commands, links, space) => {
    const created = await api.createProject(title, cwd, commands, links, space)
    await loadCommands()
    // Sin espacio elegido, el backend acaba de crear uno: si no se recarga
    // la lista, el selector del formulario siguiente no lo enseña.
    await loadSpaces()
    return created
  }

  const handleUpdateProject = async (id, title, cwd, commands, links, space) => {
    const updated = await api.updateProject(id, title, cwd, commands, links, space)
    await loadCommands()
    return updated
  }

  const handleDeleteProject = async (id) => {
    await api.deleteProject(id)
    await loadCommands()
  }

  // ---- Ejecutar un Proyecto: sesión nueva + cd + secuencia ----
  const handleRunProject = async (id) => {
    const res = await api.runProject(id)
    await assignToActiveSpace(res.name)
    await loadSessions(true)
    await handleSelect(res.name)
    focusTerminal(res.name)
  }

  // ---- Ejecutar un Proyecto en su propio espacio, en una pestaña nueva ----
  // El espacio se busca por título del proyecto y se crea si no existe, así
  // que acaba siendo un espacio dedicado a ese proyecto. De ahí que baste
  // con mirar si YA hay alguna sesión dentro para reutilizarla en vez de
  // acumular `proyecto (2)`, `proyecto (3)`... a cada clic.
  //
  // Todo el trabajo se hace ANTES de abrir la pestaña: si algo falla, el
  // error se ve aquí y no hemos dejado una pestaña huérfana a medio cargar.
  const handleRunProjectInNewTab = async (id) => {
    const proj = projects.find((p) => p.id === id)
    if (!proj) return
    const wanted = proj.title.trim().toLowerCase()
    let space = spaces.find((s) => s.title.trim().toLowerCase() === wanted)
    if (!space) space = await handleCreateSpace(proj.title)

    if (!sessions.some((s) => s.space === space.id)) {
      const res = await api.runProject(id)
      await api.assignSessionSpace(res.name, space.id)
      await loadSessions(true)
    }

    const url = `${window.location.pathname}?space=${encodeURIComponent(space.id)}`
    window.open(url, '_blank', 'noopener')
  }

  // ---- Mostrar una sesión en el grid ----
  // Ya no hay nada que "arrancar" en el servidor: la terminal se conecta
  // sola al puente PTY cuando se monta el tile. Mostrar una sesión es
  // des-ocultarla y, si vive en otro espacio, saltar a ese espacio para que
  // el clic en el sidebar nunca resulte en "no pasa nada visible".
  const handleSelect = async (name) => {
    unhideSession(name)
    const session = sessions.find((s) => s.name === name)
    // Si aún no conocemos la sesión (recién creada: `sessions` se actualiza
    // en el siguiente render) no tocamos el espacio: cambiarlo aquí nos
    // llevaría a "Sin asignar" por creer que no tiene espacio.
    if (session) {
      const target = session.space || UNASSIGNED
      if (activeSpace !== target) {
        setActiveSpace(target)
      }
    }
    setActiveName(name)
  }

  // ---- Quitar una ventana del grid ----
  // La sesión de tmux sigue viva y en el sidebar: solo deja de renderizarse
  // su terminal. Antes esto además paraba un proceso ttyd en el servidor;
  // hoy es puramente una preferencia de vista de este navegador.
  const handleClose = (name) => {
    hideSession(name)
  }

  // ---- Terminar la sesión de tmux (kill-session) desde el panel ----
  const handleKillSession = async (name) => {
    try {
      await api.killSession(name)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        handleAuthFailure()
      } else {
        setError(tError(err))
      }
    } finally {
      // La lista de sesiones cambió: al refrescarla, el tile desaparece
      // solo del grid (que se deriva de ella).
      loadSessions()
    }
  }

  // ---- Reordenar ventanas arrastrando (drag & drop) ----
  // El orden vive en una lista global de nombres. Al arrastrar, arrancamos
  // de cómo está ordenado el grid AHORA y reinsertamos: así las sesiones
  // que aún no tenían orden manual quedan fijadas en el sitio que ocupaban.
  const handleReorder = (fromName, toName) => {
    setOrder((current) => {
      const visible = openSessions.map((s) => s.name)
      const rest = current.filter((n) => !visible.includes(n))
      const from = visible.indexOf(fromName)
      const to = visible.indexOf(toName)
      if (from === -1 || to === -1 || from === to) return current
      const next = [...visible]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return persistOrder([...next, ...rest])
    })
  }

  // ---- Espacios ----
  const handleCreateSpace = async (title) => {
    const created = await api.createSpace(title)
    await loadSpaces()
    return created
  }

  const handleRenameSpace = async (id, title) => {
    const updated = await api.updateSpace(id, title)
    await loadSpaces()
    return updated
  }

  // Borrar un espacio devuelve sus sesiones a "Sin asignar" sin tocar tmux.
  // Si la pestaña lo estaba mirando, la mandamos allí para no dejarla
  // apuntando a un espacio que ya no existe (grid vacío sin explicación).
  const handleDeleteSpace = async (id) => {
    await api.deleteSpace(id)
    if (activeSpace === id) setActiveSpace(UNASSIGNED)
    await loadSpaces()
    await loadSessions()
  }

  const handleAssignSpace = async (name, spaceId) => {
    await api.assignSessionSpace(name, spaceId === UNASSIGNED ? null : spaceId)
    await loadSessions()
  }

  if (!authChecked) {
    return (
      <div className="flex h-full items-center justify-center bg-panel-bg text-panel-muted">
        {t('app.loading')}
      </div>
    )
  }

  if (!authed) {
    return <LoginScreen onSubmit={handleLogin} error={loginError} />
  }

  // `/dashboard` se resuelve mirando el `pathname`, sin router: es UNA vista
  // alternativa, y traer una biblioteca de rutas para eso sería más código que
  // el que ahorra. El backend sirve ahí el mismo index.html (ver main.py).
  //
  // No monta el grid, así que en esta pestaña no hay terminales conectadas y
  // el reloj de trabajo no cuenta: mirar los tiempos no es trabajar en un
  // proyecto.
  if (esDashboard) {
    return (
      <>
        <Dashboard spaces={spacesOrdenados} />
        <PauseQuestion hueco={workPause.pregunta} onResponder={workPause.responder} />
      </>
    )
  }

  return (
    <div className="flex h-full w-full bg-panel-bg">
      <PauseQuestion hueco={workPause.pregunta} onResponder={workPause.responder} />
      <Sidebar
        workClock={workClock}
        workPause={workPause}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
        width={sidebarWidth}
        sessions={sessions}
        commands={commandsOrdenados}
        projects={projectsOrdenados}
        openNames={openSessions.map((s) => s.name)}
        spaces={spacesOrdenados}
        activeSpace={activeSpace}
        onSetActiveSpace={setActiveSpace}
        onCreateSpace={handleCreateSpace}
        onRenameSpace={handleRenameSpace}
        onDeleteSpace={handleDeleteSpace}
        onAssignSpace={handleAssignSpace}
        loading={loading}
        error={error}
        onSelect={handleSelect}
        onHideTile={handleClose}
        onCreate={handleCreateSession}
        onRenameSession={handleRenameSession}
        onKillSession={handleKillSession}
        onRunCommand={handleRunCommand}
        onRunProject={handleRunProject}
        onRunProjectInNewTab={handleRunProjectInNewTab}
        onSaveCommand={handleSaveCommand}
        onUpdateCommand={handleUpdateCommand}
        onDeleteCommand={handleDeleteCommand}
        onSaveProject={handleSaveProject}
        onUpdateProject={handleUpdateProject}
        onDeleteProject={handleDeleteProject}
        onRefresh={loadSessions}
        onLogout={handleLogout}
        layout={layout}
        onSetLayout={changeLayout}
      />
      {!sidebarCollapsed && <Resizer orientation="vertical" onDrag={resizeSidebar} />}
      <main className="h-full flex-1 overflow-hidden">
        <SessionGrid
          openSessions={openSessions}
          activeName={activeName}
          onSetActive={setActiveName}
          onClose={handleClose}
          onKill={handleKillSession}
          onSpawn={handleSpawnTerminal}
          onRename={handleRenameSession}
          onReorder={handleReorder}
          commands={commandsOrdenados}
          projects={projects}
          layout={layout}
          focusedName={focusedName}
          onSetFocused={(name) => {
            setFocusedName(name)
            if (name) setActiveName(name)
          }}
          minimizedNames={minimizedNames}
          onToggleMinimized={toggleMinimized}
          onRestoreAllMinimized={restoreAllMinimized}
          focusName={focusReq.name}
          focusToken={focusReq.token}
        />
      </main>
    </div>
  )
}
