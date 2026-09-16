---
actualizado: 2026-09-16
archivos:
  - frontend/playwright.config.js
  - frontend/e2e/fixtures.js
  - frontend/e2e/global-setup.js
  - frontend/e2e/entorno.js
---

# Reproducir un fallo que solo se ve en el navegador

El andamiaje E2E no sirve solo para los tests que ya hay: **levanta un panel
entero —backend, datos y servidor de tmux propios— y es la forma de reproducir
casi cualquier fallo del panel sin tocar el panel vivo del usuario**. Cuando el
fallo es visual e intermitente, montar esto cuesta menos que razonarlo, y la
diferencia es que al final hay un número.

## Cómo se monta un caso

1. Un `*.spec.js` en `frontend/e2e/` (los de usar y tirar, con prefijo `zz-`, y
   se borran antes de cerrar la tarea). `bun run test:e2e <patrón>` lo corre solo.
2. La fixture `tmux` habla con el servidor del E2E. Las sesiones se crean **con
   el programa dentro** (`new-session -d -s X "python3 …"`): un `send-keys`
   contra una shell recién nacida se come caracteres.
3. Para imitar a Claude Code hace falta una TUI de mentira: pantalla alternativa
   (`\033[?1049h`), un marco vivo que se repinta en el sitio y líneas estáticas
   largas que se envuelven. Con líneas **numeradas y con cada trozo distinto**,
   una mezcla se ve a simple vista; con un patrón periódico, no.
4. Que la TUI se pueda **pausar** (una tecla que lee de `stdin`) es lo que hace
   comparables las dos pantallas: mientras escribe, cualquier diferencia puede
   ser solo que una foto es más nueva que la otra.

## El oráculo: contra qué se compara

- **Lo que pinta el navegador**: `.xterm-rows > div` y su `textContent` (ojo con
  el ` ` del relleno). Es lo que el usuario ve de verdad.
- **Lo que tiene tmux**: `capture-pane -p`. Es la verdad.
- Si difieren, el daño está en el navegador. Dos medidas que han funcionado:
  filas del navegador que no aparecen en tmux, y **filas repetidas** (un
  `Set` sobre las filas útiles) — esa segunda es la que delata el fallo clásico
  de repintado.
- Espiar el WebSocket desde Playwright (`page.on('websocket')`, `framesent` y
  `framereceived`) da los mensajes de control y **los bytes que manda tmux**,
  que es donde se ve qué está dibujando y con qué geometría.

## Reglas

- **Rojo primero.** Si el caso no falla con el código de antes, no está
  reproducido, y lo que se arregle después no se sabrá si era eso.
- El navegador se redimensiona con `page.setViewportSize`, y un tile con
  `display:none` deja el DOM **congelado**: sus filas son las de antes de
  esconderse, no un fallo.
- Nada de esto toca `backend/data/` ni el tmux del usuario: el E2E usa socket
  (`-L`) y directorio propios, y el teardown solo mata lo que lleva su prefijo.
