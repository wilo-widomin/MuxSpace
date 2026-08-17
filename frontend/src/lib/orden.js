// Orden alfabético de las listas del panel.
//
// Se aplica en el ORIGEN (App.jsx) y no en cada lista: comandos, proyectos y
// espacios se pintan en varios sitios —el selector del sidebar, el
// desplegable del tile, el filtro del dashboard— y ordenarlos en cada uno es
// garantía de que un día uno se quede sin ordenar.
//
// OJO: esto es para CATÁLOGOS. La secuencia de comandos de un proyecto es un
// orden de ejecución, no un catálogo: ordenarla alfabéticamente rompería el
// proyecto.

/**
 * Copia de `lista` ordenada por un campo de texto.
 *
 * `localeCompare` y no `<`: con `<`, "Ávila" iría después de "Zaragoza" y
 * "árbol" después de "Árbol". `numeric` hace que "sesion-2" preceda a
 * "sesion-10", que es como las lee una persona.
 */
export function porNombre(lista, campo) {
  return [...lista].sort((a, b) =>
    String(a[campo] || '').localeCompare(String(b[campo] || ''), undefined, {
      sensitivity: 'base',
      numeric: true,
    }),
  )
}
