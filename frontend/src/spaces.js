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
