// "Sin asignar" no es una fila de `spaces.json`: es, literalmente, no tener
// entrada en el mapa de asignaciones. Vive aquí (y no en App.jsx) para que
// Sidebar pueda usarlo sin importar de App, que importa Sidebar.
export const UNASSIGNED = 'unassigned'

// Valor histórico de la vista "Todas", retirada del selector. Solo se usa
// para degradar lo que quedó guardado en sessionStorage de pestañas
// abiertas antes del cambio; no queda lógica viva que lo mire.
export const LEGACY_ALL_SPACES = 'all'

// `space` de una sesión (null si no tiene) -> clave de espacio para la UI.
export const spaceKeyOf = (session) => session.space || UNASSIGNED

// Espacio con el que arranca una pestaña.
//
// `?space=<id>` es una ORDEN DE APERTURA, no el estado de la pestaña: la pone
// el botón "abrir proyecto en pestaña nueva" para decir a dónde entrar. Se
// obedece una sola vez y luego se borra de la URL (ver App.jsx); si se
// quedara, cada recarga volvería a imponer ese espacio y pisaría en silencio
// el que el usuario eligió después — que es exactamente lo que pasaba:
// recargar te devolvía al proyecto que abriste en esa pestaña hace días.
export function initialSpace(search, saved) {
  const fromUrl = new URLSearchParams(search).get('space')
  if (fromUrl) return fromUrl
  return !saved || saved === LEGACY_ALL_SPACES ? UNASSIGNED : saved
}
