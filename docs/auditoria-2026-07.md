# Auditoría de seguridad y calidad — julio 2026

Fecha: **2026-07-27**. Alcance: backend completo, frontend, scripts de
arranque y el despliegue real de esta VM (7.372 líneas).

Los hallazgos marcados **CONFIRMADO** se verificaron ejecutando contra el
backend en marcha, no leyendo el código. Las pruebas fueron contenidas y
reversibles; todo lo que crearon quedó borrado (ver S3).

Plan de corrección: [`plans/seguridad-y-qa.md`](plans/seguridad-y-qa.md).

---

## El marco: esto no es un CRUD, es una shell remota

`send-command`, `/api/commands/{id}/launch`, `/api/projects/{id}/run` y el
WebSocket del PTY ejecutan comandos arbitrarios como el usuario que corre el
backend. No hay sandbox, ni lista blanca, ni confirmación.

De ahí salen las dos consecuencias que ordenan toda la auditoría:

1. **El control de acceso es el 100% del perímetro.** No hay una segunda
   línea que limite el daño de una autenticación saltada.
2. **Cualquier fallo que permita a un tercero provocar una acción en tu
   navegador equivale a ejecución remota de código.** Un clickjacking aquí
   no es "un clic no deseado": es un comando ejecutado en tu máquina.

---

## Resumen de hallazgos

| Id | Severidad | Hallazgo | Estado |
|----|-----------|----------|--------|
| S1 | Alta | Sin cabeceras de seguridad → clickjacking a ejecución de comandos | CONFIRMADO |
| S2 | Alta *(este despliegue)* | API sin autenticación accesible desde localhost | CONFIRMADO |
| S3 | Media | Escritura fuera de las raíces vía symlink en `/api/upload` | CONFIRMADO (PoC) |
| S4 | Media | Agotamiento de memoria: el cuerpo se bufferiza antes del límite | Por lectura |
| S5 | Media-baja | Peticiones sin `Origin` pasan el guard CSRF | Por lectura |
| S6 | Baja | Cookie de sesión sin `Secure` por defecto | Por lectura |
| S7 | Baja | `CORS_ORIGINS` se parsea distinto en dos controles | Por lectura |
| S8 | Baja | Sin registro de auditoría de comandos ejecutados | Por lectura |
| S9 | Baja | Ficheros de datos con permisos 0644 | Por lectura |
| S10 | Baja | Sesiones: sin caducidad por inactividad ni revocación global | Por lectura |
| S11 | Informativo | `preexec_fn` en un proceso con hilos | Por lectura |
| S12 | Media-baja | Documentación de la API publicada sin autenticación | CONFIRMADO |
| S13 | Baja | `suggest`/`browse` listan rutas de fuera de las raíces | CONFIRMADO |
| S14 | Baja | Un bucle de symlinks devuelve 500 en vez de rechazo | CONFIRMADO |
| S15 | Baja | `UnicodeDecodeError` no capturado en los tres stores | **CORREGIDO** |
| S16 | Baja | `spaces.json` no-objeto → `AttributeError` → 500 | CONFIRMADO |
| S17 | Baja | Una sesión con nombre que empieza por `$` no se puede matar | CONFIRMADO |

**Los seis últimos (S12-S17) aparecieron al escribir los tests de la fase 2**,
no en la revisión inicial. Ninguno es de severidad alta, y ese es justo el
punto: son la clase de fallo que no se ve leyendo el código y que solo aparece
cuando alguien se pregunta "¿y si el JSON está cortado a medio carácter?".

| Hallazgo | Lo destapó |
|---|---|
| S12 | US-002, al preguntarse qué queda FUERA de su propio filtro |
| S13, S14 | US-003, en los casos de traversal |
| S15, S16 | US-006, en los casos de JSON corrupto |
| S17 | US-007, al probar el ciclo de vida contra tmux real |

S12 y S15 están corregidos. S13, S14 y S16 siguen **cubiertos por tests
`xfail(strict=True)`**: existen en la suite, no la bloquean, y el día que
alguien los arregle sin quitar el marcador se ponen en rojo. El arreglo no se
puede colar sin enterarse. S17 es el único que no tiene `xfail` sino un test
de caracterización (ver su sección).

---

## S1 · ALTA — Clickjacking → ejecución de comandos · CONFIRMADO

```console
$ curl -D- -o /dev/null http://127.0.0.1:8000/
HTTP/1.1 200 OK
date / server / content-type / accept-ranges / content-length / etag
```

Cero cabeceras de seguridad: sin `X-Frame-Options`, sin
`Content-Security-Policy`, sin `X-Content-Type-Options`.

Un sitio malicioso puede embeber `https://<dominio-del-panel>` en un iframe
invisible: el navegador presenta el certificado mTLS **automáticamente** y,
con la autenticación desactivada (S2), el panel se renderiza ya operativo.
Superponiendo un señuelo, un clic inducido sobre un ▶ de Proyectos ejecuta
esa secuencia de comandos en la máquina del usuario.

El guard de Origin (`backend/main.py:316`) **no protege de esto**: dentro
del iframe las peticiones son same-origin. `SameSite=Lax` tampoco, porque
sin sesión no hay cookie que restringir.

**Corrección** — middleware que fije en cada respuesta:

```python
resp.headers["X-Frame-Options"] = "DENY"
resp.headers["Content-Security-Policy"] = (
    "default-src 'self'; frame-ancestors 'none'; "
    "img-src 'self' data:; style-src 'self' 'unsafe-inline'; base-uri 'none'"
)
resp.headers["X-Content-Type-Options"] = "nosniff"
resp.headers["Referrer-Policy"] = "no-referrer"
```

Verificar además que el Caddy del host no las descarta. Es la corrección
con mejor relación coste/impacto de toda la auditoría.

---

## S2 · ALTA (en este despliegue) — API sin autenticación en localhost · CONFIRMADO

`backend/.env` tiene `MUXSPACE_AUTH_ENABLED=false`:

```console
$ curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/sessions
200
$ curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/commands
200
```

[`mtls.md`](../mtls.md) (sección 4) documenta los dos caminos que hay que
cerrar antes de desactivar el login, y **ambos están cerrados**: el backend
escucha solo en `127.0.0.1:8000` (verificado con `ss -ltnp`). Lo que esa
checklist no cubre es el **propio localhost**.

Y en esta VM hay superficie de sobra escuchando en `0.0.0.0`:

```
8080  8081  8001  3010  3011  8443  5432 (postgres)  8889  4000 (bun)
```

Cualquiera de esos servicios comprometido —o cualquier proceso local,
contenedor o script— llega a `127.0.0.1:8000` y obtiene una shell sin dar
un paso más. Un SSRF en cualquiera de ellos vale igual.

**Corrección** — reactivar `MUXSPACE_AUTH_ENABLED=true`. El `.env` ya tiene
`MUXSPACE_AUTH_MODE=pam`, así que no hay contraseña nueva que gestionar, y
con `SESSION_TTL_HOURS=168` supone **un login cada 7 días**. El mTLS sigue
siendo la primera puerta; esto es la segunda. La propia documentación lo
recomienda ("algo que tienes + algo que sabes") y hoy solo está la primera
mitad.

---

## S3 · MEDIA — Escritura fuera de las raíces vía symlink en `/api/upload` · CONFIRMADO (PoC)

`_unique_target` (`backend/main.py:560`) usa `target.exists()`, que **sigue
enlaces simbólicos**: ante un symlink colgante devuelve `False`, y el
`write_bytes` posterior escribe en el destino del enlace.

Prueba ejecutada (symlink, fichero de prueba y entrada de historial
borrados después):

```console
$ ln -s /tmp/.../escape-test.txt ~/.muxspace-audit-test.log   # colgante
$ curl -X POST '…/api/upload?dir=~&name=.muxspace-audit-test.log' \
       --data-binary 'PRUEBA-AUDITORIA'
200
$ cat /tmp/.../escape-test.txt
PRUEBA-AUDITORIA          # ← escrito FUERA de las raíces configuradas
```

`resolve_within_roots` valida bien la **carpeta** (resuelve enlaces antes de
comprobar contención — ese control está correcto), pero nadie valida el
**fichero final**. Explotable por quien pueda plantar un symlink en el home;
hoy, por S2, también por cualquier proceso local.

**Corrección** — abrir con `O_NOFOLLOW` (y `O_EXCL`, que de paso elimina la
carrera entre `_unique_target` y la escritura):

```python
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
```

---

## S4 · MEDIA — Agotamiento de memoria en subidas

`paste_image` (`backend/main.py:468`) y `upload_file`
(`backend/main.py:622`) hacen `data = await request.body()` y **después**
comprueban el tamaño. El límite (25 MB para capturas, 100 MB para archivos)
se aplica cuando el cuerpo ya está entero en RAM.

No hay tope por defecto ni en uvicorn ni en Caddy: un POST de varios GB
tumba el proceso. Con S2, sin credenciales.

**Corrección** — rechazar por `Content-Length` primero y leer con
`async for chunk in request.stream()`, abortando al superar el tope.

---

## S5 · MEDIA-BAJA — Peticiones sin `Origin` pasan el guard

`backend/main.py:324` (HTTP) y `backend/main.py:665` (WebSocket) dejan pasar
todo lo que no traiga cabecera `Origin`. Es una decisión documentada ("el
CSRF es un ataque de navegador") y con la autenticación activada es
razonable: `curl` necesita credenciales igualmente.

Con la autenticación desactivada, en cambio, es exactamente la puerta de S2:
un `wscat` sin `Origin` abre un terminal. Se resuelve al resolver S2.

---

## S6 · BAJA — Cookie de sesión sin `Secure`

`COOKIE_SECURE` vale `false` por defecto (`backend/config.py:92`) y no está
en el `.env` actual. Hoy no aplica (no hay sesión), pero al reactivar la
autenticación (S2) la cookie saldría sin `Secure` detrás de HTTPS.

**Corrección** — default `true`, o derivarlo de `X-Forwarded-Proto`; y
renombrar la cookie a `__Host-muxspace_session`.

---

## S7 · BAJA — Dos controles leen la misma variable de forma distinta

`backend/config.py:121` parsea `CORS_ORIGINS` con `.split(",")` **sin
`strip()`**, mientras `_ALLOWED_ORIGINS` (`backend/main.py:313`) sí
normaliza. Un espacio tras una coma rompe CORS en silencio y desalinea dos
controles que deberían leer lo mismo.

**Corrección** — usar `_get_str_list("MUXSPACE_CORS_ORIGINS", [...])`, que
ya existe justo encima en el mismo archivo.

---

## S8 · BAJA — Sin registro de auditoría

No queda traza de qué comando se ejecutó, en qué sesión, cuándo ni desde qué
IP. En un panel que da shell, es precisamente el log que se necesita el día
que pase algo.

**Corrección** — `data/audit.log` (append, un JSON por línea) en
`send-command`, `launch`, `run-project`, `create/kill/rename-session` y
`upload`.

---

## S9 · BAJA — Permisos de los ficheros de datos

Se escriben con el umask por defecto (0644): `library.json` (los comandos
del usuario), `upload_history.json`, `login_failures.json` y las capturas de
`data/pastes/` quedan legibles por cualquier usuario local.

**Corrección** — `data/` a 0700 y ficheros a 0600.

---

## S10 · BAJA — Gestión de sesiones

TTL de 7 días sin caducidad por inactividad, sin límite de sesiones
concurrentes y sin revocación global (solo se pierden al reiniciar el
backend, porque viven en memoria).

**Corrección opcional** — TTL de 24 h deslizante y un `POST /api/logout-all`.

---

## S11 · INFORMATIVO — `preexec_fn` en un proceso con hilos

`backend/pty_bridge.py:84` usa `preexec_fn=lambda: os.login_tty(slave)`. Los
endpoints síncronos de FastAPI corren en un threadpool, así que el `fork`
ocurre en un proceso multihilo: patrón documentado como inseguro (el hijo
puede bloquearse entre `fork` y `exec` si toma un lock que otro hilo tenía
cogido). Probabilidad baja, síntoma difícil de diagnosticar: una terminal
que no abre.

**Alternativa** — `os.forkpty()`.

---

## Lo que está bien hecho

No es relleno: son decisiones que suelen faltar en proyectos de este perfil
y que acotan de verdad la superficie.

- **tmux siempre por `argv`, nunca por shell** — la inyección de comandos a
  través del nombre de sesión no existe como categoría.
- `_quote_path` expande `~` **antes** de `shlex.quote`
  (`backend/tmux_service.py:110`), y el comentario explica por qué — que es
  justo lo que se pierde en el siguiente refactor.
- `resolve_within_roots` resuelve enlaces **antes** de comprobar contención:
  `../` y los symlinks de directorio están cubiertos.
- `_PASTE_NAME_RE` + `is_file()` antes del `FileResponse`: sin traversal al
  servir capturas.
- `compare_digest` en ambos factores; rate limit **persistido en disco** (un
  reinicio no lo resetea) que cubre también la vía HTTP Basic — el agujero
  clásico de este patrón.
- Baneo por CIDR con recarga en caliente por mtime; escritura atómica
  (tmp + `replace`) en `library`, `spaces` y `login_failures`.
- El backend **se niega a arrancar** con la contraseña de ejemplo.
- Cookie `HttpOnly` + `SameSite=Lax`; cero credenciales en la URL del
  WebSocket.
- **Cobertura de autenticación verificada en runtime**: recorriendo
  `app.routes`, las únicas rutas `/api` sin `require_auth` son `health`,
  `login` y `logout`. No hay ningún endpoint olvidado.

---

# Parte 2 — Calidad (QA)

## Q0 · El riesgo estructural

7.372 líneas, **0 tests, 0 CI, 0 linters**, software que ejecuta comandos
como el usuario, y una sola persona validando a ojo. Lo único automático es
`check-i18n`, y no está enganchado a ningún gate.

## Q1 · Qué probar primero

Por riesgo × probabilidad de regresión. Los cuatro primeros evitan un
incidente, no un bug:

1. **Contrato de autenticación** — test parametrizado sobre `app.routes` que
   exija `require_auth` en toda ruta `/api` salvo `{health, login, logout}`.
   Hoy pasa; el test es para que siga pasando con el endpoint número 40.
2. **`dir_suggestions`** — traversal: `../`, symlinks de directorio, rutas
   absolutas fuera de raíz, `~` de otro usuario, raíz inexistente. Es el
   módulo que decide dónde se puede escribir.
3. **`/api/upload`** — nombres inválidos, colisión ` (2)`, el symlink de S3,
   límite de tamaño, `dir` fuera de raíces.
4. **`auth`** — 5 fallos/minuto, reset de ventana, persistencia entre
   reinicios, que Basic penalice, expiración de sesión, baneo por CIDR.
5. `library_store` / `space_store` — CRUD, JSON corrupto → vacío (no
   excepción), atomicidad, validaciones.
6. `tmux_service` — con tmux real en CI: crear/renombrar/matar/duplicado, y
   `_quote_path` con espacios, `$()` y `~`.
7. **Frontend (vitest)** — `quotePath`, el acordeón del sidebar (abrir una
   cierra las demás + persistencia), `suggestName`, y que `ApiError` parsee
   `{code, params}`.
8. **E2E (Playwright), 3 casos** — login → listar → crear sesión; abrir
   terminal y ver eco; subir archivo y verificar la ruta copiada.

## Q2 · Gate de CI

GitHub Actions con dos jobs y merge bloqueado:

- **backend**: `ruff check` + `pytest --cov`.
- **frontend**: `bun install --frozen-lockfile` + `eslint` + `vitest` +
  `vite build` + `check-i18n` **como error, no como aviso**.

## Q3 · Sin linters ni formateo

No existe `bun run lint`. Añadir `ruff` (backend) y `eslint` + `prettier`
(frontend). Ejemplo de lo que pillarían hoy: `HTTPException` importado y sin
usar en `backend/main.py:19`.

## Q4 · Deuda concreta detectada de paso

- **`Sidebar.jsx`: 2.572 líneas** con 6+ componentes dentro
  (`PasteForClaude`, `UploadFiles`, `DirBrowserModal`, `Modal`,
  `CommandSelect`…). Es el archivo que más se toca y el más difícil de
  testear; extraerlos es prerrequisito práctico del punto 7 de Q1.
- **`upload_store._save` no usa tmp + `replace`** (`upload_store.py:58`), a
  diferencia de los otros tres stores: una caída a media escritura corrompe
  el historial.
- **Un solo worker de uvicorn es un requisito implícito**: los locks son de
  proceso (`threading.Lock`). Con `--workers 4` se corrompe la biblioteca
  por read-modify-write concurrente. Documentarlo o pasar a locking de
  fichero.
- **Coste del polling**: `list_sessions()` lanza `tmux start-server` **y**
  `list-sessions` en cada llamada; con refresco a 8 s son 2 procesos cada 8
  segundos **por pestaña abierta**. `start-server` solo hace falta una vez
  por proceso.
- **i18n**: 3 claves sin uso (`grid.layout_auto/cols/rows`) y falta la forma
  plural `many` en es/fr/it/pt para `sidebar.windows` y
  `spaces.confirm_delete`.

## Q5 · Definition of Done propuesto

Un cambio está terminado cuando: tiene un test que falla sin el cambio ·
`ruff` + `eslint` limpios · `check-i18n` sin errores · build verde ·
README/docs actualizados si cambia comportamiento observable · y, si toca
autenticación, rutas o ficheros, **un test de seguridad específico**.

## Q6 · Observabilidad

No hay logging estructurado ni métricas. Con el audit log de S8 y un
`logging` con nivel por entorno se cubre lo mínimo para diagnosticar sin
adjuntarse a la consola.

---

## S12 · MEDIA-BAJA — Documentación de la API sin autenticación · CONFIRMADO

```console
$ curl -s -o /dev/null -w '%{http_code} (%{size_download} bytes)\n' http://127.0.0.1:8000/openapi.json
200 (26995 bytes)
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs
200
```

`FastAPI(...)` monta `/docs`, `/redoc` y `/openapi.json` con sus valores por
defecto. Son `starlette.routing.Route`, no `APIRoute`: **no pasan por
`require_auth` y el contrato de rutas de US-002 es ciego a ellas por
construcción**. Publican el esquema completo —incluidos
`/api/commands/{id}/launch`, `/api/projects/{id}/run` y
`/api/send-command/{name}`, con sus parámetros— a cualquiera que alcance el
puerto.

No da acceso ni datos: da **reconocimiento**. En un panel que ejecuta comandos
como el usuario que lo corre, es el índice de lo que hay que atacar. Hoy queda
tras el mTLS, pero con la autenticación desactivada (S2) es directamente
accionable desde cualquier proceso local.

**Corrección** — `MUXSPACE_DOCS_ENABLED`, por defecto `false`, que pasa `None`
a `docs_url`/`redoc_url`/`openapi_url` (que **desmonta** la ruta, no solo
esconde el enlace). Regresión cubierta en `test_auth_contract.py`, con sus
propias aserciones porque el censo no las ve.

---

## S13 · BAJA — `suggest`/`browse` listan rutas de fuera de las raíces

Un symlink de directorio plantado dentro de una raíz y apuntando fuera **se
lista**, y como la abreviatura resuelve el enlace, lo que se muestra es la ruta
real del destino:

```
suggest('') -> ['/tmp/.../fuera', '/tmp/.../roots/home/sub']
                 ^^^^^^^^^^^^^^ fuera de las raíces configuradas
```

**Entrar sigue bloqueado** (`resolve_within_roots` devuelve `None`), así que no
permite leer ni escribir ahí: es filtración de rutas del sistema de ficheros.
Efecto secundario del mismo fallo: un enlace y su destino salen **duplicados**
en el desplegable.

**Corrección** — aplicar `_is_within` a cada hijo antes de listarlo
(`dir_suggestions.py`, el `items.append` de `suggest` y el `dirs` de `browse`).

Cubierto por `test_dir_roots.py::test_suggest_nunca_ofrece_algo_de_fuera_de_las_raices`,
marcado `xfail(strict=True)`: se pondrá en rojo el día que se arregle sin quitar
la marca.

---

## S14 · BAJA — Un bucle de symlinks devuelve 500

```
resolve_within_roots(raiz/bucle) -> RuntimeError: Symlink loop from '.../bucle'
browse(raiz/bucle)               -> RuntimeError: Symlink loop from '.../bucle'
```

`Path.resolve()` traduce el ELOOP a **`RuntimeError`**, no a `OSError`, que es
lo único que `resolve_within_roots` captura. La excepción sube hasta el
endpoint: **500** en vez del rechazo limpio que promete el contrato. Afecta a
`resolve_within_roots`, `browse` y `create_dir`.

Lo provoca cualquiera que pueda crear un enlace dentro de una raíz — incluido
el propio usuario sin querer. Y si una **raíz configurada** fuera un bucle,
`_resolve_roots` reventaría y se caerían a la vez el navegador de carpetas, las
sugerencias y la subida de archivos.

De paso explica por qué los `except OSError` de ese módulo no llegan a
ejercitarse: están muertos justo para el caso que los justificaba.

**Corrección** — capturar también `RuntimeError` (o `(OSError, RuntimeError)`)
en los tres puntos.

Cubierto por `test_dir_roots.py::test_un_bucle_de_symlinks_se_rechaza_sin_excepcion`,
`xfail(strict=True)`.


---

## S15 · BAJA — `UnicodeDecodeError` no capturado en los tres stores · CORREGIDO

```console
b'{"commands": [{"id": "c1", "label": "Compilaci\xc3'
  library_store.list_commands -> UnicodeDecodeError
  space_store.list_spaces     -> UnicodeDecodeError
  upload_store.list_recent    -> UnicodeDecodeError
```

Los tres leen con `read_text(encoding="utf-8")` y capturan
`(json.JSONDecodeError, OSError)`. **`UnicodeDecodeError` no es ninguna de las
dos**: es hermana de `JSONDecodeError` bajo `ValueError`.

Y no es el caso exótico: se serializa con `ensure_ascii=False` y el propio
`_default_label` mete una `…` de 3 bytes. Un `library.json` cortado en medio de
un carácter multibyte deja el panel devolviendo **500 en cada carga**.

Es el desperfecto contra el que existe el tmp + replace, visto desde el lado de
la lectura: hoy la escritura ya es atómica, así que el fichero cortado tendría
que venir de fuera (un disco lleno antes del arreglo, una edición a mano, una
restauración a medias). Pero el contrato del módulo es "leer nunca lanza", y
esto lo rompe.

**Corregido** — los tres capturan ahora `(ValueError, OSError)`, que cubre las
dos excepciones por herencia. Una línea por store.

La regresión es
`test_stores.py::test_regresion_s15_un_json_cortado_a_medio_caracter_no_hace_lanzar_la_lectura`,
parametrizado sobre los tres (ya sin `xfail`). Verificado por mutación:
devolver cualquiera de los tres `except` a `(json.JSONDecodeError, OSError)`
pone en rojo su parámetro y solo el suyo.

---

## S16 · BAJA — `spaces.json` que no es un objeto → 500 · CONFIRMADO

```console
b'[]'      -> AttributeError: 'list' object has no attribute 'get'
b'42'      -> AttributeError: 'int' object has no attribute 'get'
b'null'    -> AttributeError: 'NoneType' object has no attribute 'get'
b'"hola"'  -> AttributeError: 'str' object has no attribute 'get'
```

`space_store._read()` hace `raw.get("spaces")` sin comprobar el tipo.
`library_store` (`isinstance(data, dict)`) y `upload_store`
(`isinstance(data, list)`) **sí** comprueban: es una asimetría, no una decisión.

**Corrección** — el mismo `isinstance(raw, dict)` que ya tienen los otros dos.

Cubierto por `test_stores.py`, `xfail(strict=True)`.

---

## S17 · BAJA — Una sesión cuyo nombre empieza por `$` no se puede matar · CONFIRMADO

```console
$ tmux new-session -d -s '$MI_COMANDO'   # creada
$ tmux list-sessions                     # \$MI_COMANDO
$ tmux kill-session -t '$MI_COMANDO'     # can't find session: $MI_COMANDO
$ tmux kill-session -t normal            # OK  <- control
```

En un `-t`, tmux interpreta el `$` como prefijo de **ID de sesión**, no de
nombre. La sesión se crea y se lista con su nombre entero, pero `kill_session`
devuelve `False` y se queda ahí para siempre. Ni el prefijo `=` de coincidencia
exacta la rescata (tmux 3.4).

No es una vulnerabilidad —nada se ejecuta, porque tmux se invoca siempre por
argv— pero sí **una sesión que el panel no puede cerrar**.

**Es alcanzable desde el panel.** `_SESSION_NAME_RE`
(`^[A-Za-z0-9_-]{1,64}$`) bloquea el `$` en `/api/create-session`, pero
`_tmux_safe_label` —la que usan `/api/commands/{id}/launch` y
`/api/projects/{id}/run`— solo sustituye `[.:/\\]`:

```
label '$MI_COMANDO'  ->  nombre de sesión '$MI_COMANDO'
label '$(id) build'  ->  nombre de sesión '$(id) build'
```

Un comando de la biblioteca cuya **etiqueta** empiece por `$`, o un proyecto
cuyo **título** empiece por `$`, deja una sesión incerrable desde el panel.

**Corrección** — añadir `$` a los caracteres que sustituye `_tmux_safe_label`,
o validar el nombre resultante contra `_SESSION_NAME_RE` antes de crear.

Cubierto por `test_tmux_service.py`, `xfail(strict=True)`.
