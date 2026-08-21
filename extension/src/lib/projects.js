// Ordenar y filtrar la lista de proyectos del popup.
//
// Cálculo puro: no habla ni con Chrome ni con el panel.

/**
 * Deja un texto comparable: sin mayúsculas y sin tildes.
 *
 * Sin quitar las tildes, buscar «agencia» no encontraría «Agéncia», y quien
 * escribe deprisa en un buscador no va a poner la tilde. Y al revés: escribir
 * con tilde tiene que encontrar lo que no la lleva.
 *
 * @param {string} texto
 * @returns {string}
 */
export function normalizar(texto) {
  return String(texto ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

/**
 * Los proyectos ordenados por título.
 *
 * `localeCompare` y no `<`: con el orden de códigos, «Zapato» iría antes que
 * «ábaco» y las mayúsculas se separarían de las minúsculas, que es justo lo
 * que hace que una lista parezca desordenada aunque técnicamente no lo esté.
 *
 * @param {Array<{title: string}>} projects
 * @returns {Array} Una lista nueva; la de entrada no se toca.
 */
export function sortProjects(projects) {
  const lista = Array.isArray(projects) ? projects.slice() : []
  return lista.sort((a, b) =>
    String(a?.title ?? '').localeCompare(String(b?.title ?? ''), undefined, {
      sensitivity: 'base',
      numeric: true,
    }),
  )
}

/**
 * Los proyectos que casan con lo que se está escribiendo, ya ordenados.
 *
 * Busca **en cualquier parte del título**, no solo al principio: con nombres
 * como `SOCIAL-VIDEO-DOWNLOADER` o `AGENT-WILO.com`, lo que uno recuerda casi
 * nunca es la primera palabra.
 *
 * Con la búsqueda vacía devuelve todo, ordenado igual: el buscador filtra la
 * lista, no la sustituye.
 *
 * @param {Array<{title: string}>} projects
 * @param {string} query
 * @returns {Array}
 */
export function filterProjects(projects, query) {
  const ordenados = sortProjects(projects)
  const busqueda = normalizar(query).trim()
  if (!busqueda) return ordenados
  return ordenados.filter((p) => normalizar(p?.title).includes(busqueda))
}
