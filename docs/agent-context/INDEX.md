# Contexto del proyecto — MuxSpace

Panel web que gestiona el servidor de tmux del usuario: abre cada sesión como
una terminal en un grid, con espacios, biblioteca de proyectos y registro de
jornada.

Lee primero el dominio que corresponda a la tarea. No explores el código sin
haber mirado su documento.

| Si la tarea trata de… | Abre |
|---|---|
| sesiones de tmux, ventanas del grid, tiles, crear/renombrar/matar/cerrar terminales, orden y tamaño de las ventanas, minimizar, maximizar | `sesiones/` |
| lo que pasa dentro de la terminal: WebSocket, PTY, xterm, portapapeles, OSC 52, scroll, búsqueda, pegar texto largo, transcript de Claude | `terminal/` |
| comandos guardados, proyectos, directorio y enlaces de un proyecto, ejecutar o lanzar algo desde la biblioteca | `biblioteca/` |
| espacios, agrupar sesiones, «Sin asignar», filtrar la vista por cliente o proyecto | `espacios/` |
| avisos de que una sesión reclama, campanilla, marca en el tile, hooks que llaman al panel desde el host | `atencion/` |
| horas trabajadas, cronómetro, latidos, bloques, pausas, dashboard, informes de tiempo | `jornada/` |
| subir archivos, pegar imágenes para Claude, elegir o crear carpetas, rutas que se copian al portapapeles | `archivos/` |
| login, cookie, sesión caducada, rate-limit, IPs baneadas, auditoría, CSP y cabeceras, mTLS y certificados de dispositivo | `acceso/` |
| textos de la interfaz, traducciones, idiomas, plurales, mensajes de error que ve el usuario | `i18n/` |
| la extensión de Chrome, grupos de pestañas, abrir un proyecto desde el navegador | `extension/` |

Transversal:

- `arquitectura.md` — stack, capas, convenciones, cómo se arranca y se prueba,
  y las trampas que muerden en cualquier tarea (datos reales en
  `backend/data/`, un solo worker, `bun` nunca `npm`, recompilar `dist`).

## Mapa rápido

- `backend/` — FastAPI. Un módulo por responsabilidad, sin capas.
  `main.py` son los endpoints y los middlewares.
- `frontend/` — React + Vite + Tailwind, sin router. `src/components/` tiene el
  sidebar, el grid y la terminal.
- `extension/` — extensión de Chrome (MV3), paquete aparte.
- `scripts/` — verificador de traducciones y utilidades de mTLS.
- `docs/` — documentación humana (`muxspace.md`, `mtls.md`, historias de
  usuario). Esta carpeta es la versión para agentes, no la sustituye.
