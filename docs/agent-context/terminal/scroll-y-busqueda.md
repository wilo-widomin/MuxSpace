---
dominio: terminal
accion: scroll-y-busqueda
actualizado: 2026-09-06
archivos:
  - backend/pty_bridge.py
  - backend/tmux_service.py
  - frontend/src/components/XtermTerminal.jsx
  - frontend/src/components/TranscriptSearch.jsx
depende_de: [sesiones/_dominio]
---

# Scroll y búsqueda del historial

El historial que se recorre es el de **tmux**, no el buffer de xterm (que está
vacío: los bytes ya pasaron). Por eso la rueda, la barra propia y la búsqueda
se traducen a copy-mode de tmux por mensajes de control.

## Flujo

1. Rueda o arrastre de la barra → mensaje `scroll` / `scroll-to`.
2. `pty_bridge` entra en copy-mode y coloca la posición encadenando
   `copy-mode; send-keys scroll-up -N ...; send-keys scroll-down -N` en **una
   sola invocación de tmux** (tres fork+exec por píxel se notaban).
3. El backend responde `scroll-state` con `inMode`, `position`, `history`,
   `height` y `alternate`.
4. Búsqueda (Ctrl+F o la lupa) → mensaje `search` → copy-mode → respuesta
   `search-result` con el número de coincidencias.

## Reglas

- **`alternate_on` reparte el trabajo**: si el programa ocupa su pantalla
  alternativa (Claude Code, vim, less), el cliente no intercepta ni la rueda ni
  Ctrl+F, la barra se oculta y la lupa abre el modal del transcript. El backend
  también rechaza entrar en copy-mode con `alternate` activo.
- **En pantalla alternativa el dedo se traduce a rueda.** No hay historial de
  tmux que recorrer, pero el programa sí tiene el suyo y solo lo mueve con
  eventos de ratón: las flechas del teclado no sirven de sustituto porque el
  programa las usa para otra cosa (Claude Code, para su historial de prompts).
  El arrastre emite `wheel` sintéticos sobre el elemento de xterm y es él quien
  los codifica; el panel no interpreta nada. Fuera de pantalla alternativa el
  gesto no existe: manda la barra propia, que en táctil ya funciona.
- tmux busca en *smartcase*, así que `_patron_sin_mayusculas` convierte cada
  letra en `[aA]` y escapa los metacaracteres ERE: buscar `total (1)` literal
  fallaría si no.
- tmux no dice si encontró algo, así que `_contar_coincidencias` hace
  `capture-pane` y cuenta, para distinguir «0 resultados» de «encontrado».

## Trampas

- Con un arrastre en curso se ignora todo `scroll-state` entrante; si no, el
  pulgar salta atrás con estado viejo.
- El gesto táctil espera **10 px antes de secuestrar el arrastre**: sin ese
  umbral la tableta perdería el toque simple y la selección dentro del
  programa. Y lleva `preventDefault()` por lo de siempre — sin él, el navegador
  desplaza la página y xterm hace además su propio scroll, así que el gesto
  cuenta dos veces.
- Los `wheel` sintéticos se emiten **de fila en fila**, no por píxel: un delta
  menor que la altura de fila lo redondea xterm a cero y el gesto se pierde
  entero. El resto se guarda para el movimiento siguiente.
- `scroll-to` va throttled a 100 ms quedándose con el último (uno por
  `pointermove` repintaba el panel entero) y la rueda acumula líneas cada
  40 ms. Al soltar se pide `scroll-query` porque tmux puede haber recortado el
  salto.
- La lupa del tile es un **interruptor**, no un disparo: en una tableta no hay
  Escape. Al cerrar manda `scroll-exit` y devuelve el foco.
- En el transcript, las coincidencias se numeran **después** de filtrar; si no,
  «3 de 17» llevaría a bloques ocultos.
