---
dominio: sesiones
accion: estado-del-grid
actualizado: 2026-11-05
archivos:
  - frontend/src/App.jsx
  - frontend/src/lib/grid.js
  - frontend/src/components/SessionGrid.jsx
  - frontend/src/spaces.js
  - frontend/src/useAttentionEvents.js
  - frontend/src/lib/coalesce.js
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

## Cuándo se recarga cada lista

| Lista | Cuándo |
|---|---|
| Sesiones | sondeo cada 8 s, parado con la pestaña oculta, y tras cada acción |
| Proyectos | evento `projects-changed` del bus, al montar y tras cada acción |
| Espacios | evento `spaces-changed` del bus, al montar y tras cada acción |
| Todo lo anterior, y comandos, textos y enlaces | al reconectar el bus |

El evento solo dice qué lista ha cambiado y la lista se vuelve a pedir, así que
da igual quién hizo el cambio: un script, otro aparato u otra pestaña. El bus no
tiene memoria, y por eso reconectar lo pide todo: lo emitido con la conexión
caída se ha perdido. Una recarga no publica nada, de modo que no hay bucle, y
`coalesce` junta en una sola las ráfagas (un alta con token son dos eventos).

Lo que se está escribiendo en un formulario no se pierde: su estado vive en
`Sidebar`, y estas listas solo le llegan como propiedades.

## Reglas

- El orden manual es **una sola lista global** de nombres, no una por espacio;
  se filtra por espacio al pintar y las sesiones sin entrada van al final,
  alfabéticamente.
- Los pesos de los separadores se guardan **por forma de rejilla** (`2x2`,
  `3x2`…): unos pesos de 3 columnas no significan nada en una de 2.
- **La rejilla no deja huecos.** Si la última fila queda incompleta (3
  terminales en 2x2, 5 en 3x2), la ventana que tiene el hueco debajo se estira
  hasta la última fila. El último separador horizontal cruza solo las columnas
  que siguen partidas; encima de la ventana estirada le robaría los clics.
- `?space=<id>` es una **orden de apertura de una sola vez**: `initialSpace` la
  obedece y un efecto la borra de la URL con `replaceState`. Si se quedara,
  cada recarga te sacaría del espacio en el que trabajas.

## Trampas

- **`sesionesDelGrid` (`frontend/src/lib/grid.js`) recorta cada sesión** a los
  campos que el tile usa (`CAMPOS`: name, project, cwd, command), para que el
  `useMemo` no cambie de identidad cuando el sondeo trae algo que el grid no
  pinta. Un campo nuevo del tile **pasa por esa lista**: se ha comido ya
  `project` (badges que no salían) y `cwd` (tooltip sin directorio), y las dos
  veces el componente estaba bien y sus tests en verde.

- Minimizar y ocultar **no desmontan** el tile (CSS `display:none`):
  desmontarlo cerraría el WebSocket y perdería el scrollback de xterm. A
  cambio, la terminal escondida sigue viva y su `ResizeObserver` dispara con el
  contenedor a cero: ver la trampa de `FitAddon` en `terminal/_dominio`.
- Al abrir o cerrar una terminal cambia la forma de la rejilla, así que se
  recuperan otros tamaños. Parece que «se pierden» y no es un bug.
- Un `space` guardado en sessionStorage que ya no existe (borrado desde otra
  pestaña) deja el grid vacío: no hay saneo contra la lista cargada.
- Comandos, textos rápidos y enlaces no publican evento: solo se recargan al
  reconectar o tras una acción de esa pestaña.
- Si otro borra el proyecto que se está editando, el formulario sigue abierto y
  con lo escrito, y al guardar sale el error de que no existe.
