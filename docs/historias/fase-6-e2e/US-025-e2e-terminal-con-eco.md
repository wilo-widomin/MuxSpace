# US-025 · E2E: abrir una terminal y ver el eco

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-6-e2e | S2 |

## Historia

Como responsable del panel, quiero **un E2E que abra una terminal, escriba y
compruebe el eco**, porque es el único test que recorre el camino entero:
WebSocket → `pty_bridge` → PTY → tmux → xterm.js.

Es también la red que necesita US-021 (`forkpty`) para tocar el puente con
algo de tranquilidad.

## Criterios de aceptación

- [ ] Con una sesión de tmux abierta en el grid, la terminal se conecta y
      pinta el prompt.
- [ ] Escribir `echo hola` + Enter produce `hola` en la terminal.
- [ ] El texto se busca en el **contenido renderizado por xterm.js**, con
      espera activa hasta un timeout razonable. Nada de `sleep` fijos.
- [ ] **El WebSocket se abre sin errores de CSP** en la consola: es la
      directiva que el plan avisaba que podía romperse
      (`default-src 'self'` frente a `ws:`/`wss:`).
- [ ] Redimensionar la ventana del navegador reajusta la terminal y no
      rompe la conexión.
- [ ] Cerrar el tile cierra el WebSocket; la sesión de tmux **sigue viva**
      (es la diferencia entre cerrar la vista y matar la sesión).
- [ ] Matar la sesión desde el panel cierra la terminal.
- [ ] La sesión de prueba lleva el prefijo del andamiaje y el teardown la
      mata.

## Alcance técnico

- Un archivo de test más en el `e2e/` que crea US-024.
- Reutiliza su arranque de backend y su teardown: **no montes un segundo
  andamiaje**.

Para leer lo que pinta xterm.js, usa el DOM del terminal
(`.xterm-rows`) o la API del objeto `Terminal` si el componente la expone en
`window` para pruebas. Si necesitas exponerla, que sea **solo en modo
desarrollo** y déjalo justificado en el PR.

## Fuera de alcance

- Probar el copiado/pegado, el scrollback o los atajos de teclado.
- Rendimiento del puente.
- Cambiar `pty_bridge.py` o `XtermTerminal.jsx` (salvo la exposición mínima
  para pruebas, si se justifica).

## Dependencias

US-024.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`.

## Notas para el agente

- Es el test con más piezas móviles del proyecto: si sale inestable, la
  causa casi siempre es esperar por tiempo en vez de por condición.
- El criterio de la CSP y el WebSocket cierra formalmente el riesgo que el
  plan dejó abierto en la fase 0.1.
