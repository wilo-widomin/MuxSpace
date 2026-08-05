# Imágenes de la documentación

Aquí viven las capturas y diagramas que usan el `README.md` y los documentos
de `docs/`. Este archivo dice **qué imágenes hacen falta, para qué sirve cada
una y qué tiene que verse en ella**, para poder rehacerlas dentro de un año
sin adivinar de qué pantalla salieron.

Una captura de interfaz caduca en silencio: si cambia el frontend, la imagen
sigue compilando, sigue mergeando y sigue mintiendo — no hay test que la
tumbe. Por eso la lista es corta a propósito y cada entrada dice **qué
concepto ilustra**: cuando toques esa parte de la UI, sabes cuál hay que
rehacer.

## Convenciones

| | |
|---|---|
| Formato | `.png` para capturas, `.svg` para diagramas (el SVG se lee bien en cualquier zoom y GitHub lo renderiza) |
| Anchura | ≥ 1600 px en las capturas de pantalla completa; las de detalle, lo que ocupe el recorte |
| Peso | Por debajo de ~600 KB. Si se pasa, `optipng` o bajar a 1600 px de ancho |
| Nombre | `kebab-case`, descriptivo del **contenido**, no del sitio donde se usa (`sidebar-acordeon.png`, no `readme-2.png`) |
| Tema | Oscuro, que es el único que tiene el panel |
| Idioma | Español, para que case con el texto que las rodea |
| Marco | Solo el panel: sin barra de direcciones, sin pestañas del navegador, sin escritorio detrás |
| Texto alternativo | Obligatorio y descriptivo en el `![...]` — se lee en voz alta y sale cuando la imagen no carga |

**Antes de publicar una captura, míratela buscando lo que no debería estar**:
rutas con datos de otros proyectos, nombres de clientes, contenido de un
`audit.log`, tokens en una URL, correos. El panel enseña terminales reales, y
una captura publicada no se puede despublicar. Si hace falta, monta la escena
en sesiones de tmux creadas para la foto en vez de fotografiar tu trabajo.

## Lo que ya está

### `muxspace.png` — el panel entero

Portada del `README.md`, justo debajo del párrafo de apertura. Tres sesiones
de tmux repartiéndose el grid y la barra lateral completa a la izquierda.
Responde a "¿qué es esto?" antes de que nadie lea una línea.

Rehacer si cambia la disposición general (grid, barra lateral, cabecera).

## Lo que falta

En orden de rentabilidad. Las tres primeras son capturas —las haces tú—; la
cuarta es un diagrama que dibujo yo y aquí solo queda anotado para que no se
pierda.

### 1. `sidebar-acordeon.png` — la barra lateral en detalle

**Dónde va**: `README.md`, sección *Sidebar*.

**Qué es**: un recorte **solo de la barra lateral**, de arriba abajo. En la
captura de portada sale, pero compartiendo ancho con tres terminales: no se
lee nada. Aquí se trata de que se lean las etiquetas.

**Cómo montarla**: deja abierta la persiana de **Proyectos** con dos o tres
proyectos dentro, y las otras tres (**Comandos**, **Pegar imagen para
Claude**, **Subir archivo**) cerradas. Que arriba haya un espacio
seleccionado con varias sesiones, alguna abierta y alguna cerrada.

**Qué destacar**: que es un **acordeón** — cuatro persianas de las que solo
una está abierta a la vez. Es lo que el README cuenta en prosa y no se
entiende hasta verlo. Que se vean los cuatro títulos y el `+` de alta junto
al de Proyectos.

**Qué evitar**: nombres de proyectos con rutas de trabajo real. Inventa dos o
tres genéricos.

### 2. `login.png` — la pantalla de entrada

**Dónde va**: `docs/onboarding.md`, en el paso del primer arranque. La guía
de puesta en marcha no tiene hoy ni una imagen, y ésta es literalmente lo
primero que ve quien la sigue.

**Qué es**: la pantalla de login centrada: título, subtítulo, usuario,
contraseña y el botón de entrar.

**Cómo montarla**: sesión cerrada, ventana estrecha (no hace falta pantalla
completa: la tarjeta va centrada y sobra fondo). El campo de usuario relleno
con algo neutro, el de contraseña vacío.

**Qué destacar**: que la puerta es una sola tarjeta y no hay "entrar como
invitado" ni credenciales por defecto. Sirve además para que quien vea un
formulario distinto sepa que su despliegue no es el de la guía.

**Qué evitar**: contraseña visible aunque sea en puntos de un gestor, y el
nombre real de la máquina si sale en algún sitio.

### 3. `proyecto-modal.png` — el alta de un proyecto

**Dónde va**: `README.md`, sección de la *Biblioteca de proyectos*.

**Qué es**: el modal **Nuevo proyecto** abierto y relleno: *Título*,
*Directorio* y la lista de *Comandos (en orden)* con dos o tres entradas y el
`+ añadir comando` debajo.

**Cómo montarla**: barra lateral → persiana **Proyectos** → el `+` del
título. Rellena algo reconocible pero inventado (título `demo`, directorio
`~/proyectos/demo`, comandos tipo `git pull`, `bun run dev`).

**Qué destacar**: que un proyecto es **directorio + secuencia de comandos en
orden**, que es el concepto que más cuesta pillar leyendo el README, y que al
ejecutarlo el título pasa a ser el nombre de la sesión de tmux.

**Qué evitar**: rutas reales en el campo de directorio — sale entero y
legible.

### 4. `arquitectura.svg` — el diagrama de flujo *(lo hago yo)*

**Dónde va**: `README.md`, sección *Arquitectura*, sustituyendo al dibujo
ASCII de las líneas del bloque de código.

**Qué es**: el camino Navegador → FastAPI → PTY → `tmux attach`, en SVG y con
la frontera del proceso marcada.

**Qué destacar**: lo que el ASCII no puede decir — que por la misma conexión
y el mismo origen viajan dos cosas distintas (JSON de la API y **bytes
crudos** del terminal), que no se abre un puerto por sesión ni hay iframes, y
que el `tmux` con el que se habla es el del usuario que corre el backend.

Es la única imagen de la lista que **no caduca** cuando alguien toca la UI,
así que es también la que más aguanta el esfuerzo de hacerla bien.

## Lo que a propósito no pedimos

- **Una captura por cada modal o formulario.** El coste no es hacerlas, es
  que envejecen todas a la vez y nadie las revisa. Se ilustra el concepto
  (qué es un proyecto), no el inventario de pantallas.
- **GIFs o vídeo de la terminal en marcha.** Pesan, no se pueden leer en
  diagonal y no se pueden diffear. Lo que hay que demostrar —que la terminal
  es real y que cerrarla no mata la sesión— ya lo demuestran los tests de
  extremo a extremo, que además fallan cuando deja de ser verdad.
- **Capturas del panel tras un proxy con TLS o con mTLS.** Se ven idénticas;
  lo que cambia está en el navegador y en la configuración, no en la
  interfaz.
