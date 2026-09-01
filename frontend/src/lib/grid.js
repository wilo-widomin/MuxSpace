// Qué sesiones se ven en el grid, en qué orden y con qué campos.
//
// Vive fuera de `App.jsx` porque es la pieza que ya se ha comido dos campos:
// primero `project` (y las badges de enlaces no aparecían nunca) y luego
// `cwd` (y el tooltip del tile salía sin el directorio). Aquí es una función
// pura y con test; dentro del `useMemo` no la cubría nadie.

// Campos que el grid necesita de cada sesión. Se recorta a propósito: así el
// `useMemo` no cambia de identidad cuando el sondeo trae un campo que el grid
// no pinta, y no se re-renderiza el grid entero por nada. Añadir un campo
// nuevo al tile PASA POR AQUÍ.
const CAMPOS = ['name', 'project', 'cwd', 'command']

/**
 * Sesiones del espacio activo que no están ocultas, ya ordenadas.
 *
 * @param {Array} sessions - catálogo completo tal y como llega de la API.
 * @param {string} activeSpace - espacio que mira esta pestaña.
 * @param {string} unassigned - valor que representa «Sin asignar».
 * @param {Set<string>} hidden - nombres de las ventanas cerradas por el usuario.
 * @param {Array<string>} order - orden manual, una sola lista global.
 * @returns {Array} objetos recortados a los campos que el grid usa.
 */
export function sesionesDelGrid(sessions, activeSpace, unassigned, hidden, order) {
  const inSpace = sessions.filter((s) =>
    activeSpace === unassigned ? !s.space : s.space === activeSpace,
  )
  const visible = inSpace.filter((s) => !hidden.has(s.name))
  // Orden manual primero; las que no aparecen en él (sesiones nuevas) van
  // al final, alfabéticamente, en vez de en un orden arbitrario.
  const rank = new Map(order.map((name, i) => [name, i]))
  return visible
    .slice()
    .sort((a, b) => {
      const ra = rank.has(a.name) ? rank.get(a.name) : Infinity
      const rb = rank.has(b.name) ? rank.get(b.name) : Infinity
      if (ra !== rb) return ra - rb
      return a.name.localeCompare(b.name)
    })
    .map((s) => Object.fromEntries(CAMPOS.map((campo) => [campo, s[campo] ?? null])))
}
