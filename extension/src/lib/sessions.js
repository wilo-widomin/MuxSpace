// Qué sesiones de tmux corresponden a un proyecto.
//
// Cálculo puro sobre lo que devuelve `/api/sessions`: no habla con Chrome ni
// con el panel.

/**
 * ¿Hay que lanzar el proyecto, o ya tiene una terminal viva?
 *
 * Reabrir un grupo NO puede crear una sesión más cada vez: el panel numera
 * las repetidas (`Panel (2)`, `Panel (3)`...) y a la quinta apertura el
 * espacio sería un muro de terminales iguales. Se lanza solo si no queda
 * ninguna del proyecto — porque se mató, o porque es la primera vez.
 *
 * @param {Array<{project?: string|null}>} sessions - Lo que da `/api/sessions`.
 * @param {string} projectId
 * @returns {boolean}
 */
export function needsLaunch(sessions, projectId) {
  if (!projectId) return false
  const lista = Array.isArray(sessions) ? sessions : []
  return !lista.some((s) => s?.project === projectId)
}

/**
 * Sesiones del proyecto que están fuera de su espacio.
 *
 * Las que se lanzaron antes de que el proyecto tuviera espacio se quedaron en
 * «Sin asignar». Con eso, abrir el proyecto lleva a un espacio vacío aunque
 * su terminal esté viva y a dos palmos: `needsLaunch` ve que ya hay una y no
 * lanza otra (bien), pero nadie la trae. Abrir el proyecto es encontrarse sus
 * terminales, así que se mueven.
 *
 * Solo se tocan las que son SUYAS. Una sesión suelta que el usuario creó a
 * mano no se arrastra a ningún sitio.
 *
 * @param {Array<{name: string, project?: string|null, space?: string|null}>} sessions
 * @param {string} projectId
 * @param {string|null} spaceId - Espacio del proyecto.
 * @returns {string[]} Nombres de las sesiones que hay que mover.
 */
export function sessionsToAdopt(sessions, projectId, spaceId) {
  if (!projectId || !spaceId) return []
  const lista = Array.isArray(sessions) ? sessions : []
  return lista
    .filter((s) => s?.project === projectId && (s?.space || null) !== spaceId)
    .map((s) => s.name)
}
