# Documento de Especificación: MuxSpace

## 1. Visión General

MuxSpace es una interfaz web centralizada para gestionar, visualizar y
organizar múltiples sesiones de **tmux** de forma simultánea desde el
navegador. No es un emulador de terminal propio: es un panel de control
sobre el servidor tmux del usuario que ejecuta el backend.

Alcance del producto:

- **Catálogo y ciclo de vida de sesiones** de tmux (listar, crear,
  abrir/cerrar vista, renombrar, separar *detach*, enviar comandos y
  destruir).
- **Grid responsivo** que muestra varias terminales a la vez, cada una con
  su propia instancia de **xterm.js** conectada por WebSocket a un puente
  PTY del backend que ejecuta `tmux attach`.
- **Biblioteca reutilizable** de **comandos** (una línea de shell) y
  **proyectos** (directorio + secuencia de comandos) que se pueden lanzar
  en sesiones nuevas con un clic. Persiste en disco entre reinicios.
- **Autenticación** HTTP Basic opcional sobre el dashboard y la API.
- **Autocompletado de directorios** acotado a las raíces configuradas.

Diseñado para instalarse en cualquier Linux: un único proceso sirve la
API, el WebSocket de las terminales **y** el frontend compilado, todo en
un solo puerto local. No depende de systemd, Docker ni de ningún proxy
(estos son opcionales para exponerlo al exterior).

## 2. Arquitectura del Sistema

Tres capas que se comunican entre sí, más un almacenamiento persistente.

### Capa de Control (Backend — Python / FastAPI)

- Expone la API REST y el WebSocket de las terminales.
- Encapsula toda la interacción con el binario de `tmux` (listar, crear,
  renombrar, destruir, *detach*, `send-keys`).
- Abre un **pseudo-terminal (PTY)** por terminal abierta y ejecuta
  `tmux attach -t <sesión>`, transmitiendo los bytes en ambos sentidos por
  WebSocket. No lanza ningún proceso externo por sesión (sustituye al
  antiguo enfoque con `ttyd`).
- Mantiene un **registro en memoria** de qué sesiones están "abiertas en el
  grid" para reconstruirlo al recargar la página (sin estado de tmux).
- Persiste la biblioteca de comandos/proyectos en JSON plano.

### Capa de Presentación (Frontend — React + Tailwind + Vite + xterm.js)

- Layout principal: **Sidebar** (anchura resizable, por defecto 20 %) y
  **Grid** (resto).
- El Sidebar tiene dos zonas: arriba el catálogo de **Sesiones**
  (colapsable); abajo dos **secciones fijas y redimensionables** entre sí:
  **Comandos** y **Proyectos**. Los formularios de creación/edición se
  abren en un **modal** central.
- El Grid reparte el espacio a partes iguales entre las terminales abiertas.
- Cada terminal es un componente **xterm.js** propio (no un `<iframe>`),
  lo que permite controlar la selección y la copia al portapapeles desde el
  propio cliente.

### Capa de Transporte (Protocolo)

- **HTTP/REST** para la API y la carga inicial.
- **WebSocket** (`/api/terminal/{name}`) para el flujo bidireccional de
  bytes de la terminal:
  - cliente → servidor (binario): *stdin* del teclado.
  - cliente → servidor (texto/JSON): control, p. ej. `{"type":"resize","cols":…,"rows":…}`
    y el scroll del historial (`scroll`, `scroll-to`, `scroll-query`,
    `scroll-exit`).
  - servidor → cliente (binario): *stdout* del terminal.
  - servidor → cliente (texto/JSON): estado, hoy solo
    `{"type":"scroll-state","position":…,"history":…,"height":…}`.
- Todo por el **mismo origen** que la API; no se abren puertos adicionales
  por sesión.

### Almacenamiento

- `backend/data/worklog.db` (SQLite) guarda el registro de tiempo de trabajo:
  una fila por ranura de 30 s, con la ranura como clave primaria (ver 3.G).
- `backend/data/commands.json` y `backend/data/library.json` guardan la
  biblioteca de comandos y proyectos. El directorio `data/` se crea
  automáticamente al primer escritorio y está fuera de git (datos del
  usuario).

```
Navegador ──HTTP──────> FastAPI (API + frontend estático)
 (xterm.js) ──WebSocket─> /api/terminal/{sesión} ──PTY──> tmux attach -t <sesión>
                                    │
                                    └── subprocess ──> tmux (list/new/kill/...)
```

## 3. Comportamiento de la Interfaz (UX)

### A. Sidebar

- **Sesiones**: catálogo de sesiones activas de tmux. Al hacer clic en una,
  se abre en el grid. Ofrece crear sesiones nuevas (con un comando opcional
  de la biblioteca y/o un directorio) y acciones por sesión (renombrar,
  *detach*, enviar comando, destruir).
- **Comandos** (sección fija inferior, redimensionable): biblioteca de
  comandos de una línea. Crear/editar/borrar y **lanzar** en una sesión
  nueva. El formulario vive en un modal.
- **Proyectos** (sección fija inferior, redimensionable): biblioteca de
  proyectos (título + directorio + secuencia de comandos). Crear/editar/
  borrar y **ejecutar** en una sesión nueva (hace `cd <cwd>` y lanza los
  comandos en orden dentro del mismo shell).
- La anchura del Sidebar es arrastrable; un divisor vertical controla el
  reparto de alto entre las secciones fijas.

### B. Grid Dinámico (Auto-Layout)

- CSS Grid equitativo: el espacio se reparte a partes iguales entre las
  terminales abiertas (1 sesión = 100 %; 4 sesiones = 2×2; etc.).
- Cada *tile* tiene una cabecera con el nombre de la sesión y un control de
  cierre (**X**) que retira la vista del grid (no destruye la sesión de
  tmux).
- El cliente envía el tamaño real del tile al backend, que ajusta el PTY
  (`TIOCSWINSZ`) para que tmux redibuje en ese tamaño.

### C. Terminal y portapapeles

- La selección con el ratón y `Ctrl/Cmd+C` copian al portapapeles del
  sistema (`navigator.clipboard`); `Ctrl/Cmd+V` y el clic central pegan.
- Se interpreta **OSC 52**: si una app dentro de tmux (vim, etc.) fija el
  portapapeles, también llega al del sistema. Para ello el backend activa
  en cada sesión, *best-effort*, `allow-passthrough on` y
  `set-clipboard on` (se ignoran errores en tmux antiguos).
- **El ratón de tmux está en `off` a propósito** (`set -g mouse off` en el
  `~/.tmux.conf` de la máquina, que no se versiona). Con `mouse on`, tmux
  captura el arrastre y xterm.js nunca llega a tener una selección del
  navegador: el copiar-al-seleccionar deja de funcionar. Fue un bug real de
  este panel, así que **no se toca**.

### D. Scroll del historial

- tmux ocupa la **pantalla alternativa**, de modo que el scrollback propio de
  xterm.js está siempre vacío: todo el historial vive dentro de tmux y solo
  se alcanza por su *copy-mode*. Por eso la rueda no movía nada y no había
  barra que enseñar.
- Con el ratón en off (ver arriba), el gesto lo traduce el cliente: la rueda y
  la barra que pinta el propio componente mandan `scroll` / `scroll-to` por el
  WebSocket, y el backend los convierte en `copy-mode -e` + `send-keys -X`.
  tmux devuelve la posición en un `scroll-state` y con eso se dibuja la barra.
- **Teclear vuelve al final**: si el usuario está mirando el historial, el
  puente cancela el copy-mode antes de inyectar la pulsación. Si no, las
  teclas se las comería el copy-mode y la terminal parecería colgada.
- **Quién se queda la rueda lo decide `alternate_on`**, que viaja en el
  `scroll-state`. Si el programa del panel ocupa *su* pantalla alternativa
  (Claude Code, vim, less), tmux no guarda ni una línea de eso: el cliente no
  intercepta la rueda y xterm.js la traduce a flechas para que scrollee el
  programa. Solo cuando el panel está en la pantalla normal entran en juego
  el copy-mode y la barra.
- La barra se pinta con `z-20`: xterm.js apila sus capas hasta `z-index: 10`,
  así que sin eso queda debajo del terminal, invisible y sin recibir clics.

### E. Búsqueda en el historial

- **Ctrl/Cmd+F** abre una caja de búsqueda sobre la terminal. Enter salta a la
  coincidencia anterior (lo más reciente primero), Mayús+Enter deshace el
  camino y Esc cierra y vuelve al final.
- La resuelve la búsqueda del **copy-mode de tmux** (`search-backward` /
  `search-forward`), por el mismo canal de control. El buscador de xterm.js no
  sirve aquí por lo mismo que no servía su scrollbar: su buffer está vacío. El
  **resaltado de coincidencias lo pinta tmux** (`copy-mode-match-style`).
- En pantalla alternativa **no se intercepta el atajo**: ahí no hay historial
  de tmux, y Ctrl+F es del programa (Claude Code, vim…), no del panel.
- No debe confundirse con el desplegable **▶** de la cabecera del tile: ese
  filtra la **biblioteca de comandos** y ejecuta el que elijas; no mira el
  contenido de la terminal.

### F. Redactar textos largos

- El icono del **lápiz** abre un modal con un área de texto donde **Enter es
  un salto de línea**. Existe porque en una TUI como Claude Code Enter envía,
  y un mensaje de varios párrafos no se puede escribir ahí dentro.
- **«Pegar en la terminal»** usa `term.paste()`, no un `write` de los bytes:
  paste aplica el **pegado con corchetes** cuando el programa lo pide, y eso
  es lo que hace que la TUI trate veinte líneas como *un* pegado en vez de
  como veinte pulsaciones de Enter. Deja el texto en el prompt; no envía.
- Al cerrar, el texto queda en el portapapeles, y el borrador se guarda **por
  sesión** en `localStorage` para que cerrar sin querer no cueste el texto.

### G. Registro de tiempo de trabajo

Mide **horas del usuario por espacio**, para poder decidir cuántos proyectos
caben en paralelo con una fecha comprometida. No mide tiempo transcurrido: un
espacio puede estar abierto ocho horas mientras un agente construye y el
usuario trabaja en otro.

- **La salida del terminal NO es actividad.** Es la regla que da sentido a
  todo lo demás: con el agente construyendo, el PTY escupe texto durante
  minutos con el usuario en otra pestaña. Si esos bytes contaran, el registro
  mediría exactamente las horas que **no** se trabaja. El cliente solo mira
  entrada del usuario (`keydown`, `mousemove`, `click`, `scroll`,
  `touchstart`) y no toca el WebSocket del puente.
- Un espacio acumula cuando se cumplen **las dos**: el documento tiene el
  **foco** y ha habido entrada en los últimos **3 minutos**. El foco solo no
  basta (dejar la pestaña abierta e irse a comer apuntaría 45 minutos falsos).
- **Latido, no arranque/parada.** El cliente late cada **30 s** mientras está
  activo; el servidor redondea a una ranura de 30 s y la guarda con la ranura
  como **clave primaria**. Un cierre sucio cuesta una ranura, no un tramo
  abierto de ocho horas, y dos pestañas (o dos dispositivos) colapsan en la
  misma ranura: el invariante «la suma de los espacios nunca supera el tiempo
  transcurrido» lo **impide el esquema**, no lo vigila un test.
- **No hay acumulados.** El total se deriva contando ranuras al leer.
- La hora la pone el **servidor**: el reloj del navegador metería horas en el
  día equivocado sin forma de detectarlo. Los totales por día se agrupan por
  **día local** (el desfase viaja en la petición), porque en UTC la jornada se
  parte a las 02:00.
- Junto a la ranura se guarda qué programa corría en la sesión mirada
  (`pane_current_command`), lo que permite separar **horas con un agente
  delante** de horas de terminal a secas.
- **Precisión objetivo ±15 %.** Hay dos sesgos conocidos que se compensan:
  leer sin tocar nada más de 3 minutos resta, y seguir contando hasta 3
  minutos tras la última tecla suma. Afinar uno solo empeora el dato.
- **Cronómetro en la cabecera del sidebar** (y en el rail plegado): **verde**
  cuando el tiempo se mide, **ámbar** cuando se declara, apagado si no cuenta.
- **Tiempo medido y tiempo declarado.** El detector no puede ver el trabajo
  que ocurre *fuera* del panel —probar en otra pestaña la app que construyes—,
  porque ahí no hay ni foco ni entrada que medir. Para eso está el cronómetro:
  al encenderlo, cuenta **sin exigir foco**. Cada ranura guarda cómo se supo
  (`source`: `auto` o `manual`) y el dashboard los enseña por separado; si un
  día el total no cuadra con lo que uno recuerda, lo primero que hay que poder
  saber es qué parte se midió y qué parte se declaró.
- El modo declarado es **renovable, no indefinido**: cualquier entrada tuya en
  el panel, o volver a su pestaña, reinicia la cuenta; **30 minutos** sin que
  aparezcas y se apaga solo. Además, si el navegador ofrece detección de
  presencia (Chrome, con permiso y en contexto seguro), deja de contar cuando
  el sistema dice que te has ido o la pantalla está bloqueada. Sin esa API, la
  caducidad es la única red, y basta.
- Con foco y entrada, **lo medido manda**: esa ranura se guarda como `auto`
  aunque el interruptor esté encendido.
- **`/dashboard`** (icono de barras, abre en pestaña nueva) muestra totales
  por espacio y por día. Necesita ruta propia en el backend porque
  `StaticFiles` devuelve 404 para lo que no es un archivo; `App.jsx` decide la
  vista mirando el `pathname`, sin router.
- Almacenamiento: **SQLite** en `backend/data/worklog.db`. Los stores en JSON
  se reescriben enteros en cada cambio, y esto son ~1000 ranuras por jornada.
- Se registra **que** hubo entrada, nunca **qué** se tecleó.

## 4. Flujo de Trabajo (Logic Flow)

1. **Consulta:** el frontend pide la lista de sesiones (`GET /api/sessions`)
   y la sincroniza cada 8 s; carga además la biblioteca (`/api/commands`,
   `/api/projects`).
2. **Activación:** al clicar una sesión, `POST /api/start-session/{name}` la
   marca como abierta en el registro.
3. **Puente:** el frontend añade un tile con xterm.js que abre un WebSocket a
   `/api/terminal/{name}`. El backend valida la sesión existe, abre un PTY y
   ejecuta `tmux attach -t <name>`, reenviando bytes en ambos sentidos.
4. **Resize:** el cliente notifica el tamaño del tile; el backend aplica
   `TIOCSWINSZ` y tmux se ajusta.
5. **Desactivación:** al pulsar la **X**, el frontend retira el tile y llama
   a `POST /api/stop-session/{name}`. La sesión de tmux sigue viva; solo se
   cierra la vista.
6. **Biblioteca:** un comando o proyecto puede lanzarse en una sesión nueva
   (`/api/commands/{id}/launch`, `/api/projects/{id}/run`); el backend crea
   la sesión con `tmux new-session -d` e inyecta el comando vía
   `send-keys`.

## 5. Ventajas de esta Estructura

- **Un solo puerto / un solo origen:** API, WebSocket y frontend sirven
  desde el mismo proceso y puerto. Sin puertos por sesión, sin iframes.
- **Escalabilidad visual:** puedes tener decenas de sesiones de tmux en
  segundo plano y solo abrirlas en el grid cuando las necesites.
- **Independencia:** si la web se recarga, el estado de tmux permanece
  intacto; solo se cierran las vistas.
- **Portapapeles nativo:** al usar xterm.js propio (y no un iframe de
  terceros) el cliente controla la copia/pegado y el OSC 52.
- **Biblioteca reutilizable:** comandos y proyectos repetitivos se lanzan
  con un clic y sobreviven a reinicios del backend.

## 6. Consideraciones de Seguridad

Dado que el panel expone terminales por web, se aplica:

- **Autenticación HTTP Basic** opcional (`MUXSPACE_AUTH_ENABLED`). El
  WebSocket del puente PTY valida el mismo token base64 por *query param*
  `?token=` (el navegador no permite fijar cabeceras en el *handshake* WS).
- **Sin puertos extra ni iframes:** todo por el mismo origen
  (`/api/terminal/...`).
- **Bind local por defecto** (`MUXSPACE_HOST=127.0.0.1`). Para exponerlo
  al exterior, pon un *reverse proxy* (Caddy/Nginx) delante con TLS y, si
  procede, deja que el proxy gestione la auth; entonces enlaza el backend a
  `0.0.0.0`.
- **Autocompletado de directorios acotado:** las sugerencias solo listan
  bajo las raíces configuradas (`MUXSPACE_DIR_SUGGESTION_ROOTS`, `~` =
  home del usuario que corre el backend), no exponen zonas arbitrarias del
  sistema de ficheros.

## 7. Configuración y despliegue

- Toda la configuración vive en variables de entorno (ver `backend/.env.example`
  y la tabla del `README.md`). El backend carga `backend/.env` por ruta
  explícita, de modo que los valores del despliegue no estén hardcodeados
  en el código y el repo sea 100% genérico.
- **Producción:** `./start.sh` prepara el venv, compila el frontend si falta
  y arranca uvicorn sirviendo API + frontend en un solo puerto.
- **Desarrollo:** `./scripts/dev.sh` arranca backend y frontend (Vite HMR)
  por separado.
- Puede envolverse en un servicio de systemd (u otro supervisor) para que
  arranque con el usuario y se reinicie solo; el proxy queda fuera del
  alcance del propio panel.