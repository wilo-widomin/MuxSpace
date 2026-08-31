---
dominio: atencion
actualizado: 2026-08-31
archivos:
  - backend/attention_store.py
  - backend/events.py
  - backend/main.py
  - frontend/src/useAttentionEvents.js
  - frontend/src/lib/chime.js
  - frontend/src/App.jsx
  - frontend/src/components/TerminalTile.jsx
  - frontend/src/components/Sidebar.jsx
  - scripts/muxspace-attention.sh
depende_de: [sesiones/_dominio, terminal/_dominio, acceso/_dominio]
---

# Atención

Una sesión **reclama** al usuario: un agente que espera respuesta, un script
que termina. Se marca desde dentro de la sesión, en el host, y el panel lo
enseña como punto ámbar que late (tile y sidebar), una campanilla corta y un
contador en el título de la pestaña. La marca se apaga al atender esa
terminal.

Documentación para humanos: `docs/avisos-de-atencion.md`.

## Piezas

- `attention_store.py` — el mapa `sesión -> aviso`, **en memoria**, más el
  secreto que autoriza a marcar (`data/attention_token`, 0600, creado en el
  arranque).
- `events.py` — bus en proceso. Reparte a las pestañas suscritas y no guarda
  nada.
- `main.py` — `POST/DELETE /api/attention/{name}`, `DELETE /api/attention`, el
  WebSocket `/api/events` y el campo `attention` de `SessionInfo`.
- `useAttentionEvents.js` — el WebSocket del cliente, con reconexión.
- `chime.js` — la campanilla, sintetizada con WebAudio (no hay .wav).
- `scripts/muxspace-attention.sh` — lo que llama un hook de Claude Code,
  instalado en `~/.claude/settings.json` (todos los proyectos).

## Invariantes

- **El estado vive en el servidor**, y es la excepción consciente a "todo lo
  del grid es estado de cliente" (ver `sesiones/_dominio`). Lo que se guarda
  no es una vista: es un hecho del servidor. De ahí las dos propiedades que
  el usuario nota — el aviso sobrevive a cerrar el tile y a recargar, y
  apagarlo en un dispositivo lo apaga en todos.
- **Un aviso es un estado, no una cola.** Marcar dos veces refresca; no
  acumula. Diez avisos seguidos siguen siendo una señal que se apaga con un
  gesto.
- **El bus solo adelanta la noticia.** La fuente de verdad es
  `GET /api/sessions`. Perder la conexión retrasa el aviso al siguiente
  sondeo, nunca lo pierde.
- El secreto del host autoriza a **marcar y nada más**: ni listar, ni apagar.
- Los avisos **no se persisten**: reiniciar el backend los borra, como las
  sesiones de login.

## Trampas

- **`/api/attention/{name}` (POST) no declara `require_auth`**, y por eso
  aparece enumerada en `RUTAS_CON_SECRETO_DEL_HOST` en
  `test_auth_contract.py`. Su dependencia es `main._attention_auth`, que cae
  en `require_auth` cuando el secreto no vale. El DELETE del mismo path sí lo
  declara: la excusa es por ruta, no por path.
- **El sondeo del listado se para con la pestaña oculta.** Es la razón de que
  exista `/api/events`; "usar el sondeo y ya" rompe justo el caso para el que
  se hizo la función.
- **El audio nace bloqueado.** Sin un gesto previo del usuario en la pestaña,
  `chime()` no suena y no avisa de nada. `armChime()` se engancha al primer
  clic o tecla del panel por eso.
- `onActivity` de `XtermTerminal` va por **ref espejo**: el efecto principal
  depende solo de `[name]` y meterlo en las dependencias recrearía la
  terminal y su WebSocket (ver `terminal/_dominio`).
- El token se genera en el `lifespan`, no al primer uso: un hook que se
  instala antes de que nadie haya marcado tiene que poder leer el fichero.
- **`--quiet` separa "no aplica" de "falla".** El hook es global: corre en
  cada proyecto y en cada terminal, también fuera de tmux y con el panel
  apagado. Sin tmux, sin token o con el panel sin responder (curl 7 y 28) sale
  0 y callado; un 401 sigue saliendo ruidoso con su código. Quitar esa
  distinción da a elegir entre un error rojo por cada sesión de fuera del
  panel, o un aviso mal configurado que nadie descubre.
- **El nombre de sesión va codificado en la URL.** No son slugs: los que
  nacen de un proyecto llevan espacios y paréntesis (ver `sesiones/_dominio`),
  y curl rechaza la URL antes de salir a la red. El script lo codifica byte a
  byte con `LC_ALL=C`, que es lo que hace falta para que un acento no salga
  partido.
- Marcar **no comprueba que la sesión exista** en tmux. Quien marca corre
  dentro de ella; un `list-sessions` de por medio solo añadiría una forma de
  perder el aviso.
