# Documento de Especificación: Tmux Panel

## 1. Visión General

Tmux Panel es una interfaz web centralizada para gestionar, visualizar y
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
  - cliente → servidor (texto/JSON): control, p. ej. `{"type":"resize","cols":…,"rows":…}`.
  - servidor → cliente (binario): *stdout* del terminal.
- Todo por el **mismo origen** que la API; no se abren puertos adicionales
  por sesión.

### Almacenamiento

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

- **Autenticación HTTP Basic** opcional (`TMUX_PANEL_AUTH_ENABLED`). El
  WebSocket del puente PTY valida el mismo token base64 por *query param*
  `?token=` (el navegador no permite fijar cabeceras en el *handshake* WS).
- **Sin puertos extra ni iframes:** todo por el mismo origen
  (`/api/terminal/...`).
- **Bind local por defecto** (`TMUX_PANEL_HOST=127.0.0.1`). Para exponerlo
  al exterior, pon un *reverse proxy* (Caddy/Nginx) delante con TLS y, si
  procede, deja que el proxy gestione la auth; entonces enlaza el backend a
  `0.0.0.0`.
- **Autocompletado de directorios acotado:** las sugerencias solo listan
  bajo las raíces configuradas (`TMUX_PANEL_DIR_SUGGESTION_ROOTS`, `~` =
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