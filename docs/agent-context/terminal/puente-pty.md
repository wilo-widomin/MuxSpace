---
dominio: terminal
accion: puente-pty
actualizado: 2026-09-16
archivos:
  - backend/pty_bridge.py
  - backend/main.py
  - frontend/src/components/XtermTerminal.jsx
depende_de: [acceso/_dominio, sesiones/_dominio]
---

# Puente PTY y protocolo del WebSocket

`GET ws /api/terminal/{name}`: el backend engancha un `tmux attach` a un PTY y
hace de puente con la terminal del navegador.

## Handshake

Comprobaciones en este orden exacto, todas cerrando con **1008**: IP baneada →
`Origin` fuera de `CORS_ORIGINS` → cookie de sesión inválida → la sesión de
tmux no existe. Después `accept()`, `_prepare_session(name)` y el puente.

El WebSocket **no pasa por los middlewares HTTP**: esos controles están
duplicados a mano en el endpoint. Tocar uno sin el otro abre un agujero.

## Mensajes

| Sentido | Frame | Contenido |
|---|---|---|
| cliente → servidor | binario | stdin crudo |
| cliente → servidor | texto JSON | `resize`, `scroll`, `scroll-to`, `scroll-query`, `scroll-exit`, `search` |
| servidor → cliente | binario | stdout del PTY (lecturas de hasta 64 KB) |
| servidor → cliente | texto JSON | `resized`, `scroll-state`, `search-result` |

El resize se dispara en `ws.onopen`, en `requestAnimationFrame`, en
`document.fonts.ready` y en un `ResizeObserver` **con debounce de 60 ms**: sin
ese debounce, arrastrar un separador del grid manda ~60 resizes por segundo y
por ventana.

**El cambio de tamaño es de ida y vuelta**: el navegador solo PIDE el tamaño y
lo aplica cuando el backend confirma con `resized` que el PTY ya lo tiene. El
orden es el arreglo de un fallo caro; está entero en
[tamaño de la terminal](tamano-de-la-terminal.md) y no se toca sin leerlo.

## Reglas

- Tamaño inicial: `_tamano_para_engancharse()` consulta la ventana de tmux para
  engancharse **sin** redimensionarla; con `window-size latest` habría dos
  SIGWINCH y el prompt se reimprimiría duplicado. Fallback 24x80.
- Límites: scroll ±500 líneas por mensaje, aguja de búsqueda a 200 caracteres,
  llamadas a tmux con `timeout` de 5 s (2 s la de tamaño).
- Al cerrar: SIGTERM, espera de 2 s en pasos de 10 ms, luego SIGKILL.

## Trampas

- **`os.forkpty()` y no `Popen(preexec_fn=...)`**: los endpoints síncronos
  corren en threadpool, el fork ocurre en un proceso multihilo y un
  `preexec_fn` en Python puede colgar al hijo antes del exec — terminal en
  blanco y sin error. En el hijo todo va precalculado y se sale siempre por
  `os._exit(127)`.
- **No comprobar `out_task.done()` al principio del bucle es deliberado**: con
  forkpty el fallo del hijo solo se ve como PTY terminado, y comprobarlo tras
  un `receive()` que nunca llega colgaba el puente.
- El `receive()` en vuelo **debe** cancelarse en el `finally`, o la conexión no
  se suelta hasta que pase el recolector.
- Si estás en el historial hay que salir de copy-mode **antes** de escribir los
  bytes, o el copy-mode se come las teclas.
- **Un desajuste de geometría de un instante no se arregla solo**, porque tmux
  dibuja por diferencias contra el estado que cree que tiene el cliente. Es la
  razón de que el tamaño lo confirme el backend: `tamano-de-la-terminal.md`.
