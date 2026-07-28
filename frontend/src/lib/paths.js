// Utilidades de rutas del panel.
//
// Vive fuera de `Sidebar.jsx` porque es lógica pura: no depende de React ni
// del DOM, la usan dos componentes distintos (`PasteForClaude` y
// `UploadFiles`) y se puede probar sin montar nada.

// Las rutas se copian listas para pegar en una terminal: si llevan espacios
// o cualquier carácter que el shell interpretaría, van entrecomilladas (y con
// escape de lo que sigue siendo especial dentro de comillas dobles).
export function quotePath(path) {
  if (!/[^\w@%+=:,./~-]/.test(path)) return path
  return `"${path.replace(/(["$`\\])/g, '\\$1')}"`
}
