---
dominio: sesiones
accion: estado-del-grid
actualizado: 2026-08-28
archivos:
  - frontend/src/App.jsx
  - frontend/src/components/SessionGrid.jsx
  - frontend/src/spaces.js
depende_de: [espacios/_dominio]
---

# Estado del grid

Qué ventanas se ven, en qué orden y con qué tamaños. Nada de esto es estado de
servidor: `openSessions` se deriva de `sessions` × espacio activo × ocultas ×
orden, y por eso ningún sondeo puede reabrir una ventana que el usuario cerró.

## Dónde vive cada trozo

| Estado | Sitio | Por qué ahí |
|---|---|---|
| Espacios y a qué espacio va cada sesión | servidor | organización duradera y compartida entre dispositivos |
| Espacio que mira ESTA pestaña | `sessionStorage` `muxspace:active-space` | dos pestañas pueden ver cosas distintas |
| Ventanas ocultas, orden manual, disposición, tamaños | `localStorage` | sobrevive a recargar, es del dispositivo |
| Maximizada, minimizadas, activa, petición de foco | memoria | son del momento, no de la sesión de trabajo |

Claves de `localStorage`: `muxspace:hidden-sessions`, `muxspace:session-order`,
`muxspace:grid-layout`, `muxspace:grid-sizes:{cols}x{rows}`, `sidebarCollapsed`,
`muxspace-sidebar-width`.

## Reglas

- El orden manual es **una sola lista global** de nombres, no una por espacio;
  se filtra por espacio al pintar y las sesiones sin entrada van al final,
  alfabéticamente.
- Los pesos de los separadores se guardan **por forma de rejilla** (`2x2`,
  `3x2`…): unos pesos de 3 columnas no significan nada en una de 2.
- `?space=<id>` es una **orden de apertura de una sola vez**: `initialSpace` la
  obedece y un efecto la borra de la URL con `replaceState`. Si se quedara,
  cada recarga te sacaría del espacio en el que trabajas.

## Trampas

- Minimizar y ocultar **no desmontan** el tile (CSS `display:none`):
  desmontarlo cerraría el WebSocket y perdería el scrollback de xterm.
- Al abrir o cerrar una terminal cambia la forma de la rejilla, así que se
  recuperan otros tamaños. Parece que «se pierden» y no es un bug.
- Un `space` guardado en sessionStorage que ya no existe (borrado desde otra
  pestaña) deja el grid vacío: no hay saneo contra la lista cargada.
