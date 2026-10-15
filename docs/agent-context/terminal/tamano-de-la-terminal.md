---
dominio: terminal
accion: tamano-de-la-terminal
actualizado: 2026-10-12
archivos:
  - frontend/src/components/XtermTerminal.jsx
  - frontend/src/components/XtermTerminal.test.jsx
  - frontend/e2e/terminal.spec.js
  - frontend/src/uiScale.js
  - frontend/src/components/ScalePicker.jsx
  - backend/pty_bridge.py
depende_de: [terminal/puente-pty, sesiones/estado-del-grid]
---

# Tamaño de la terminal

Cuántas filas y columnas tiene cada terminal, y quién decide cuándo cambian.
Es el punto más delicado del puente: un desajuste de un instante entre lo que
cree tmux y lo que tiene xterm **no se arregla solo**, y deja la pantalla del
navegador con la misma línea repetida decenas de veces.

## El ciclo, y por qué es de ida y vuelta

1. El `ResizeObserver` del contenedor dispara (debounce de 60 ms) y `refit()`
   **mide** con `fit.proposeDimensions()`.
2. El cliente **solo pide** ese tamaño: `{type:'resize', cols, rows}`. No toca
   el suyo.
3. `pty_bridge` aplica el `ioctl` y encola `{type:'resized', cols, rows}` **en
   la misma cola que la salida del PTY y sin ceder el bucle**: el aviso cae
   exactamente entre los bytes que tmux dibujó con la geometría vieja y los que
   dibujará con la nueva.
4. Al recibirlo, el cliente hace `term.write('', () => term.resize(...))`: el
   `write` vacío no pinta nada y su callback se ejecuta cuando xterm ha
   terminado de procesar lo que tenía en cola, que es justo lo dibujado con la
   geometría vieja.

## Reglas

- **`FitAddon` solo mide.** `fit.fit()` está prohibido aquí: cambia el tamaño
  de xterm en el acto, que es exactamente lo que rompe la pantalla.
- Un tamaño igual al último pedido **no se reenvía**: tmux redibujaría de
  balde en cada latido del observador.
- Si la primera medida sale en blanco (la fuente aún no ha cargado) o el
  WebSocket todavía no está abierto, **se reintenta** (hasta 40 veces, cada
  60 ms). Sin eso la terminal se quedaba con los 80x24 con los que nació el
  PTY: el `ResizeObserver` ya no vuelve a dispararse si el tile no cambia.
- Un tile con `display:none` (minimizado, o escondido por el modo foco) **no
  mide ni pide nada**: `refit()` sale en cuanto `offsetWidth` u `offsetHeight`
  valen 0.

- **El margen de 4 px a cada lado va en el `div` exterior**, nunca en el
  contenedor que se le da a xterm: `FitAddon` lee el ancho calculado de ese
  contenedor y, con `box-sizing: border-box`, un padding suyo contaría como
  sitio para columnas que luego no caben. Lo vigila el E2E «el texto deja
  margen a los dos lados de la ventana».

- **El tamaño de letra sale de `uiScale.js`**: 13 px por el tamaño elegido en
  Ajustes (100 % a 200 %, de 10 en 10, guardado en `localStorage` de cada aparato). Al
  cambiarlo, la terminal recibe `muxspace:scale`, cambia `fontSize` y vuelve a
  medir: el `ResizeObserver` no se entera si el tile no cambia de tamaño.
  El resto del panel crece solo porque va en `rem`, iconos incluidos: su
  `width`/`height` se escribe en `rem` (16 px → `1rem`), nunca en píxeles.

## Trampas

- **La última letra salía cortada** (medido en el Mac de Willy, al 100 % y al
  150 %, y en el Chromium del E2E a 2560 px). xterm da a cada letra una
  separación de centésimas de píxel para cuadrarla con la celda, pero el
  navegador ya la pinta a ese ancho: en 200 o 300 columnas la fila acaba 1 a
  4 px más allá. xterm recorta cada fila a su ancho, así que se perdía media
  letra. `index.css` quita ese recorte (`.xterm-rows > div`) y el sobrante cae
  en el margen. La separación no se toca: va letra a letra.

- **tmux dibuja por diferencias**, con la posición del cursor y los márgenes de
  scroll (`DECSTBM`) del cliente como estado compartido. Si el cliente cambia
  de tamaño por su cuenta, xterm reinicia esos márgenes y tmux sigue dibujando
  contra un estado que ya no existe. Medido: 29 a 50 de 55 filas pasan a ser
  copias de la misma. Y **no lo recuperan** ni `refresh-client` ni el repintado
  que tmux hace al redimensionar: solo recargar la página u otro cambio de
  tamaño. De ahí todo lo anterior.
- **`FitAddon` no mide píxeles: lee `getComputedStyle` del contenedor.** Con un
  ancestro en `display:none` el navegador NO resuelve los porcentajes y
  devuelve el literal del CSS —aquí `h-full w-full`, o sea «100%»—, que el
  addon convierte en 100 px: unas 11 columnas por 5 filas. Sin la guarda de
  tamaño, minimizar una ventana le mandaba ese 11x5 a tmux.
- El daño de un desajuste vive **solo en el navegador**: `tmux capture-pane`
  sigue teniendo el contenido bueno. Es la forma de distinguir este fallo de
  uno del programa que corre dentro.
- Reproducirlo a mano es inútil: hace falta salida continua durante el cambio
  de tamaño. Ver `reproducir-en-e2e.md`.
