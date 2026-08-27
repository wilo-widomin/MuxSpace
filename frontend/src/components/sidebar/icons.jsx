// Iconos compartidos entre `Sidebar.jsx` y los componentes que salieron de
// él. Existen aquí y no en `Sidebar.jsx` por una razón concreta: `SpacesBar`
// los necesita, y si se quedaran en el sidebar habría que importarlos desde
// allí — o sea, `Sidebar` importa `SpacesBar` y `SpacesBar` importa de
// `Sidebar`. Un ciclo de imports que hoy funcionaría por casualidad y
// reventaría el día que alguien cambie el orden de evaluación.
//
// `CloseIcon` y `FolderIcon` siguen en `Modal.jsx`, que es una incoherencia
// conocida: moverlos obligaría a tocar los cuatro archivos que los importan,
// y esta extracción no va de reordenar iconos.

export function PlusIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

export // Icono de lápiz (estilo lucide "pencil"): renombrar.
function PencilIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </svg>
  )
}

export // Icono de check (estilo lucide "check"): confirmar renombrado.
function CheckIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

export // Icono de espacio: cuatro nodos unidos por un anillo, uno en el punto
// medio de cada lado. Es el control de "mover a otro espacio" en la fila de
// sesión, donde antes había un desplegable con el nombre del espacio escrito.
//
// El trazo del anillo se corta al llegar a cada nodo (cuatro segmentos en
// vez de un rectángulo entero): si no, la línea cruzaría los cuadrados por
// dentro y a este tamaño el dibujo se convierte en una mancha.
//
// Más grande y más fino que los demás iconos de la fila (16/1.5 frente a
// 13/2) por la misma razón: tiene ocho trazos donde un lápiz tiene dos, así
// que con el grosor de los otros se emborrona. Al ser más fino, el peso
// visual acaba pareciéndose al del resto pese a medir más.
function SpaceIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <rect x="9" y="17" width="6" height="4" rx="1" />
      <rect x="2" y="10" width="6" height="4" rx="1" />
      <rect x="16" y="10" width="6" height="4" rx="1" />
      <path d="M9 5H6.5A1.5 1.5 0 0 0 5 6.5V10" />
      <path d="M15 5h2.5A1.5 1.5 0 0 1 19 6.5V10" />
      <path d="M19 14v3.5a1.5 1.5 0 0 1-1.5 1.5H15" />
      <path d="M5 14v3.5A1.5 1.5 0 0 0 6.5 19H9" />
    </svg>
  )
}

export // Icono de papelera (estilo lucide "trash-2").
function TrashIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  )
}

// Cronómetro (estilo lucide "timer"): estado del registro de tiempo. Cuando
// cuenta, se rellena la aguja para que el estado no dependa solo del color.
export function ClockIcon({ activo = false }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="10" y1="2" x2="14" y2="2" />
      <line x1="12" y1="14" x2={activo ? '16' : '12'} y2={activo ? '11' : '9'} />
      <circle cx="12" cy="14" r="8" />
      {activo && <circle cx="12" cy="14" r="2" fill="currentColor" stroke="none" />}
    </svg>
  )
}

// Pausa / reanudar (estilo lucide "pause"/"play"): declarar la ausencia.
// El estado no depende solo del color: en pausa se ve el triángulo de
// «reanudar», que es lo que el botón hará si se pulsa.
export function PauseIcon({ pausado = false }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {pausado ? (
        <polygon points="6 3 20 12 6 21 6 3" fill="currentColor" />
      ) : (
        <>
          <rect x="6" y="4" width="4" height="16" />
          <rect x="14" y="4" width="4" height="16" />
        </>
      )}
    </svg>
  )
}

// Barras (estilo lucide "bar-chart-3"): la vista de tiempos.
export function ChartIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 3v18h18" />
      <rect x="7" y="12" width="3" height="6" />
      <rect x="12" y="8" width="3" height="10" />
      <rect x="17" y="4" width="3" height="14" />
    </svg>
  )
}
