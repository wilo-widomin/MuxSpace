// Cliente de la API del backend.
//
// Autenticación por sesión de servidor: POST /api/login abre la sesión y
// el backend la mantiene en una cookie HttpOnly que el navegador adjunta
// solo en cada petición (y en el WebSocket del terminal). El cliente no
// guarda ni ve nunca la contraseña. Un 401 indica sesión ausente/expirada.

// Un error del backend NO trae texto para el usuario: trae `{code, params}`
// y lo traduce el cliente (ver `backend/errors.py` y `src/i18n/`). Para
// pintarlo se usa `tError(err)` del hook `useT()`, nunca `err.message`
// —que aquí es el propio código, útil solo en la consola.
//
// `technical` es texto SIN traducir (stderr de tmux y demás): acompaña al
// mensaje localizado como detalle secundario.
export class ApiError extends Error {
  constructor(status, detail = null) {
    const coded =
      detail && typeof detail === 'object' && typeof detail.code === 'string'
        ? detail
        : null
    super(coded ? coded.code : typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.code = coded ? coded.code : null
    this.params = coded?.params || {}
    this.technical = coded?.technical || null
  }
}

async function request(path, options = {}) {
  const res = await fetch(path, options)

  if (!res.ok) {
    // Un 401 se sigue leyendo como cualquier otro error: el login devuelve
    // ahí `err.bad_credentials`, y cortar antes de mirar el cuerpo dejaría
    // ese caso con el genérico "No autorizado".
    let detail =
      res.status === 401
        ? { code: 'err.unauthorized' }
        : { code: 'err.http', params: { status: res.status } }
    try {
      const body = await res.json()
      // Solo aceptamos el formato con código. Un `detail` con otra forma
      // (p. ej. la lista de errores de validación de FastAPI) no es texto
      // presentable, así que se queda el genérico con el código HTTP.
      if (body.detail && typeof body.detail === 'object' && body.detail.code) {
        detail = body.detail
      }
    } catch {
      // sin cuerpo JSON
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/api/health'),
  // ---- Sesión / login ----
  login: (username, password) =>
    request('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request('/api/logout', { method: 'POST' }),
  me: () => request('/api/me'),
  listSessions: () => request('/api/sessions'),
  // Conversación de la sesión de Claude que corre en ese panel, para poder
  // buscarla: lo que Claude ya sacó de pantalla no está en ningún buffer del
  // terminal (ocupa la pantalla alternativa), pero sí en su transcript.
  getTranscript: (name) =>
    request(`/api/terminal/${encodeURIComponent(name)}/transcript`),
  createSession: (name, body) =>
    request(`/api/create-session/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }),
  // Espacios: agrupan sesiones por cliente/categoría. Qué se ve en el grid
  // es estado del cliente (ver App.jsx); aquí solo viaja la organización.
  listSpaces: () => request('/api/spaces'),
  createSpace: (title) =>
    request('/api/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  updateSpace: (id, title) =>
    request(`/api/spaces/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  deleteSpace: (id) =>
    request(`/api/spaces/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  // `space` a null devuelve la sesión a "Sin asignar".
  assignSessionSpace: (name, space) =>
    request(`/api/sessions/${encodeURIComponent(name)}/space`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ space }),
    }),
  killSession: (name) =>
    request(`/api/kill-session/${encodeURIComponent(name)}`, {
      method: 'POST',
    }),
  detachSession: (name) =>
    request(`/api/detach-session/${encodeURIComponent(name)}`, {
      method: 'POST',
    }),
  renameSession: (name, newName) =>
    request(`/api/rename-session/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: newName }),
    }),
  sendCommand: (name, command) =>
    request(`/api/send-command/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    }),
  // ---- Biblioteca: comandos (una línea) ----
  listCommands: () => request('/api/commands'),
  createCommand: (label, command) =>
    request('/api/commands', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: label || '', command }),
    }),
  updateCommand: (id, label, command) =>
    request(`/api/commands/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label, command }),
    }),
  launchCommand: (id) =>
    request(`/api/commands/${encodeURIComponent(id)}/launch`, {
      method: 'POST',
    }),
  deleteCommand: (id) =>
    request(`/api/commands/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  // ---- Biblioteca: proyectos (dir + secuencia de comandos) ----
  listProjects: () => request('/api/projects'),
  createProject: (title, cwd, commands) =>
    request('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, cwd: cwd || null, commands: commands || [] }),
    }),
  updateProject: (id, title, cwd, commands) =>
    request(`/api/projects/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, cwd: cwd || null, commands }),
    }),
  runProject: (id) =>
    request(`/api/projects/${encodeURIComponent(id)}/run`, {
      method: 'POST',
    }),
  deleteProject: (id) =>
    request(`/api/projects/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  // ---- Pegar imagen para compartir con Claude ----
  // Sube los bytes crudos de la imagen; el Content-Type indica el formato.
  // Devuelve { filename, path } con la ruta absoluta guardada en el host.
  pasteImage: (blob) =>
    request('/api/paste-image', {
      method: 'POST',
      headers: { 'Content-Type': blob.type || 'application/octet-stream' },
      body: blob,
    }),
  // Lista las capturas guardadas (máx. 5, la más nueva primero).
  listPastes: () => request('/api/pastes'),
  // URL para pintar la miniatura de una captura concreta desde disco.
  pasteThumbUrl: (filename) => `/api/pastes/${encodeURIComponent(filename)}`,
  // Borra una captura concreta.
  deletePaste: (filename) =>
    request(`/api/pastes/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    }),
  // ---- Autocompletado de directorios ----
  dirSuggestions: (q) =>
    request(`/api/dir-suggestions?q=${encodeURIComponent(q || '')}`).then((r) =>
      r && Array.isArray(r.items) ? r.items : [],
    ),

  // ---- Subir archivos a una carpeta elegida ----
  // Navega las subcarpetas de `path` (vacío = primera raíz configurada).
  // Devuelve { path, parent, dirs } en forma abreviada (~/...).
  dirBrowse: (path) =>
    request(`/api/dir-browse?path=${encodeURIComponent(path || '')}`),
  // Crea una subcarpeta `name` dentro de `parent`. Devuelve { path }.
  dirCreate: (parent, name) =>
    request('/api/dir-create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent, name }),
    }),
  // Sube los bytes crudos de un archivo a la carpeta `dir`. Devuelve
  // { name, path, dir } con la ruta absoluta guardada en el host.
  uploadFile: (file, dir) =>
    request(
      `/api/upload?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(
        file.name,
      )}`,
      {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      },
    ),
  // Historial de las últimas subidas (máx. 5, la más reciente primero).
  listUploads: () => request('/api/uploads'),
  // Quita una entrada del historial (no borra el archivo). Devuelve la lista.
  deleteUpload: (path) =>
    request(`/api/uploads?path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),
}
