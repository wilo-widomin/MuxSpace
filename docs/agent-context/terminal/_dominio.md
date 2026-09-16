---
dominio: terminal
actualizado: 2026-09-16
archivos:
  - backend/pty_bridge.py
  - backend/claude_transcript.py
  - frontend/src/components/XtermTerminal.jsx
  - frontend/src/components/TextComposer.jsx
  - frontend/src/components/TranscriptSearch.jsx
depende_de: [sesiones/_dominio, acceso/_dominio]
---

# Terminal

Sirve cada sesión de tmux como terminal interactiva en el navegador: el backend
abre un PTY con `tmux attach` y transmite bytes por WebSocket a un xterm.js
propio. Encima añade lo que un iframe de ttyd no permitía: portapapeles del
sistema, scroll y búsqueda del historial traducidos a copy-mode, redactor de
texto largo y búsqueda del transcript de Claude Code.

## Piezas

- `backend/pty_bridge.py` — el puente. `os.forkpty()` + `tmux attach`.
- `frontend/src/components/XtermTerminal.jsx` — WebSocket, portapapeles, OSC 52,
  rueda, barra de scroll propia y búsqueda.
- `TextComposer.jsx` — texto largo que se pega de una vez; Enter es salto de
  línea y solo Escape cierra. Borrador en `localStorage` por sesión.
- `TranscriptSearch.jsx` + `backend/claude_transcript.py` — copia de la
  conversación de Claude Code leída del `.jsonl`; **no mueve la vista de
  Claude**.

## Invariantes

- **Salida siempre en frames binarios, control siempre en frames de texto
  JSON.** El cliente nunca escribe en pantalla un frame de texto.
- El WebSocket se autentica con la **cookie de sesión del handshake**; no hay
  token en la URL. Todo rechazo cierra con code 1008, sin distinguir causa.
- El PTY solo se redimensiona por mensaje de control (`ioctl TIOCSWINSZ`,
  clamp 1..1000); valores basura se descartan sin tumbar la terminal.
- **El navegador nunca cambia el tamaño de xterm por su cuenta**: mide, lo pide
  y espera el `resized` del backend. Ver `puente-pty.md`.
- **Un tile que no se ve no manda tamaño.** `refit()` sale sin hacer nada si el
  contenedor mide 0 (`offsetWidth`/`offsetHeight`), porque `display:none` no es
  un tamaño nuevo, es la ausencia de tamaño.
- Cerrar la vista no mata la sesión: al cerrar el WS se manda SIGTERM al
  `tmux attach`, que solo desengancha ese cliente, y se hace `waitpid`
  obligatorio (con `forkpty` nadie cosecha el hijo: si no, zombis).

## Acciones documentadas

- [Puente PTY y protocolo del WebSocket](puente-pty.md)
- [Scroll y búsqueda del historial](scroll-y-busqueda.md)

## Trampas

- **`mouse on` de tmux está descartado a conciencia**: con el ratón capturado
  por tmux, arrastrar deja de generar selección de xterm y se rompe el
  copiar-al-seleccionar. Por eso el scroll viaja como mensajes de control.
- **OSC 52**: el payload es `<sel>;<base64>` y hay que decodificar con
  `TextDecoder('utf-8')`; hacerlo directo convierte los acentos en mojibake. El
  backend activa `allow-passthrough on` y `set-clipboard on` en cada apertura,
  best-effort e ignorando errores de tmux antiguos.
- **Shift+Enter manda `\n` (0x0a), no `\r`**: un terminal pierde la
  modificación de Enter, así que Claude Code y opencode obligarían a Ctrl+J.
  `\n` es exactamente lo que produce Ctrl+J, así que no depende de que el
  programa entienda ninguna secuencia especial. Se probó antes con `ESC`+`CR`
  (lo que configura `/terminal-setup` en iTerm2) y **no funcionó a través de
  tmux**. Se aplica siempre, también fuera de pantalla alternativa.
  **Necesita `preventDefault()`**: devolver `false` en el manejador solo evita
  que xterm procese el `keydown`, pero el navegador sigue emitiendo el
  `keypress` y xterm mandaba su `\r` justo detrás; el programa recibía salto de
  línea Y envío. Es la misma trampa que ya documenta el atajo de búsqueda.
- **No se intercepta Ctrl/Cmd+V**: xterm.js ya gestiona el pegado nativo;
  añadirlo pegaría dos veces. El clic derecho sí pega a mano.
- `onActivity` (teclear = atender un aviso, ver `atencion/_dominio`) entra por
  ref espejo, no como dependencia, por lo que dice el punto siguiente.
- El efecto principal de `XtermTerminal` depende **solo de `[name]`**: meterle
  otra dependencia (el `t` del i18n, por ejemplo) recrearía la terminal y el
  WebSocket al cambiar de idioma. De ahí las refs espejo.
- El pegado usa `term.paste()` y no una escritura de bytes: `paste` aplica
  bracketed paste, que es lo que hace que una TUI trate 20 líneas como un
  pegado y no como 20 Enter.
- **`FitAddon` solo se usa para medir (`proposeDimensions`), nunca para
  redimensionar (`fit`)**: `fit()` cambia el tamaño de xterm en el acto, que es
  justo lo que rompía la pantalla.
- **`FitAddon` no mide píxeles: lee `getComputedStyle` del contenedor.** Con un
  ancestro en `display:none` el navegador NO resuelve los porcentajes y
  devuelve el literal del CSS —aquí `h-full w-full`, o sea «100%»—, que el
  addon convierte en 100 px: unas 11 columnas por 5 filas. Sin la guarda de
  tamaño, minimizar una ventana (o maximizar otra, que oculta todas las demás)
  le mandaba ese 11x5 a tmux, que redibujaba la sesión a 11 columnas y metía en
  el historial líneas partidas y repetidas. Al restaurar se recupera el tamaño,
  pero lo que ya se escribió estrecho se queda así.
- `z-20` en la barra de scroll no es decorativo: xterm.css apila hasta 10 y sin
  eso la barra queda invisible y sorda a los clics.
