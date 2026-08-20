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
