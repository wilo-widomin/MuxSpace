# Plan de implementación — seguridad y calidad

Estado: **ejecutado y completo** (2026-07-27 → 2026-07-29).

Las seis fases están mergeadas: 26 historias de usuario, PR #3 a #39, más el
trabajo de cierre de los PR #40 a #49. Los 17 hallazgos de seguridad y los
cuatro puntos de calidad (Q1, Q2, Q3, Q4 y Q6) quedan cerrados, con 554 tests
de backend, 28 de frontend y 32 de extremo a extremo.

**Cerrado también Q6 (observabilidad).** Fue el último en caer, y por poco se
queda fuera: aparecía en el alcance de la fase 5 pero ninguna historia lo
recogió —US-018 lo dejó explícitamente fuera («esto es el log de auditoría,
no el de la app») y no se escribió otra que lo cubriera—. Se anotó aquí como
hueco pendiente en vez de dar el plan por completado, y se implementó a
continuación en el PR #43: `backend/logs.py`, con `MUXSPACE_LOG_LEVEL`.

Se cuenta así, y no se borra la historia, porque el modo de fallo es lo
interesante: un punto del plan que ninguna historia recoge no lo reclama
nadie, y marcar el plan como «hecho» lo habría enterrado para siempre.

Resuelve los hallazgos de [`../auditoria-2026-07.md`](../auditoria-2026-07.md).
Cada fase es autónoma y mergeable por separado; el orden está elegido para
que lo que más reduce riesgo entre primero y lo más lento (pruebas) no
bloquee las correcciones.

## Criterio de priorización

El panel ejecuta comandos como el usuario que corre el backend, así que el
orden lo fija el daño potencial, no la elegancia:

1. Cerrar los caminos que llevan a **ejecución de comandos por un tercero**
   (Fase 0).
2. Cerrar los que permiten **escribir fuera de sitio o tumbar el proceso**
   (Fase 1).
3. Poner la **red de seguridad** para que 1 y 2 no se deshagan solos
   (Fases 2 y 3).
4. Lo demás (Fases 4-6).

## Vista general

| Fase | Contenido | Hallazgos | Esfuerzo |
|------|-----------|-----------|----------|
| 0 | Cabeceras de seguridad + reactivar autenticación | S1, S2, S5 | ~1 h |
| 1 | Correcciones de código | S3, S4, S6, S7, S9 | ~3 h |
| 2 | Andamiaje pytest + tests de seguridad | Q1.1-Q1.6 | 1-2 días |
| 3 | CI bloqueante + linters | Q2, Q3 | ~3 h |
| 4 | Vitest + trocear `Sidebar.jsx` | Q1.7, Q4 | 1 día |
| 5 | Audit log y deuda técnica | S8, S10, S11, Q4, Q6 | ~1 día |
| 6 | E2E con Playwright (opcional) | Q1.8 | ~1 día |

---

## Fase 0 — Cortafuegos inmediato

Lo único que hay que hacer hoy. Dos cambios, ningún refactor.

### 0.1 · Cabeceras de seguridad (S1)

Nuevo middleware en `backend/main.py`, junto a `_csrf_origin_guard`:

```python
# Cabeceras de seguridad. La clave es `frame-ancestors 'none'`: sin ella,
# una web maliciosa puede embeber el panel en un iframe invisible (el
# navegador presenta el certificado mTLS solo) y convertir un clic
# inducido en la ejecución de un proyecto. El guard de Origin no cubre
# ese caso: dentro del iframe todo es same-origin.
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp
```

`style-src 'unsafe-inline'` es necesario: xterm.js inyecta estilos en línea.
No hace falta `'unsafe-inline'` en `script-src` — el build de Vite no genera
scripts inline.

**Verificación**:

```bash
curl -sD- -o /dev/null http://127.0.0.1:8000/ | grep -i 'frame\|policy\|nosniff'
```

Comprobar en el navegador (consola sin errores de CSP): terminal que pinta,
miniaturas de capturas, subida de archivos y **el WebSocket**. Si el WS
falla, añadir `connect-src 'self' ws: wss:` explícito.

**Y comprobar que el Caddy del host no las descarta** — si añade sus propias
cabeceras con `header`, `setdefault` del backend no gana ahí.

### 0.2 · Reactivar la autenticación (S2, S5)

En `backend/.env`: `MUXSPACE_AUTH_ENABLED=true` (el modo `pam` ya está
configurado, no hay contraseña nueva que gestionar).

Riesgo a validar antes de dar por cerrada la fase: en modo PAM el helper
`unix_chkpwd` tiene que poder verificar la contraseña del usuario del
backend. Probar el login **antes** de cerrar la sesión actual del navegador,
para no quedarse fuera:

```bash
curl -si -X POST http://127.0.0.1:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"willy","password":"..."}' | head -3
```

Si PAM diera problemas, alternativa inmediata: `MUXSPACE_AUTH_MODE=env` con
`MUXSPACE_PASSWORD=$(openssl rand -base64 24)`.

Tras activarlo, `MUXSPACE_COOKIE_SECURE=true` en el `.env` (el panel se sirve
por HTTPS desde el host) — ver 1.3.

**Verificación**: `curl http://127.0.0.1:8000/api/sessions` debe devolver
401, no 200.

---

## Fase 1 — Correcciones de código

### 1.1 · `O_NOFOLLOW` en la subida (S3)

`backend/main.py`, en `upload_file`. Sustituir `target.write_bytes(data)`:

```python
try:
    # O_NOFOLLOW: si `target` es un symlink, falla en vez de escribir en
    # su destino (que puede estar fuera de las raíces). O_EXCL cierra
    # además la carrera entre _unique_target y esta escritura.
    fd = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
except FileExistsError as exc:
    raise http_error(409, "err.upload_exists") from exc
except OSError as exc:
    raise http_error(500, "err.upload_failed") from exc
with os.fdopen(fd, "wb") as fh:
    fh.write(data)
```

Requiere `import os` en `main.py` y la clave `err.upload_exists` en los 6
locales (`check-i18n` lo detecta si falta).

**Verificación**: el PoC de la auditoría (S3) debe devolver 4xx y **no**
crear el fichero destino.

### 1.2 · Límite de tamaño antes de bufferizar (S4)

Helper compartido para `paste_image` y `upload_file`:

```python
async def _read_capped(request: Request, max_bytes: int) -> bytes:
    """Lee el cuerpo abortando en cuanto supera el tope.

    `await request.body()` bufferiza el cuerpo ENTERO antes de que
    podamos mirarlo: un POST de varios GB tumba el proceso aunque el
    límite sea de 100 MB.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise http_error(413, "err.upload_too_large", mb=max_bytes // (1024 * 1024))
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise http_error(413, "err.upload_too_large", mb=max_bytes // (1024 * 1024))
        chunks.append(chunk)
    return b"".join(chunks)
```

### 1.3 · Cookie `Secure` por defecto (S6)

`backend/config.py:92`: `COOKIE_SECURE` pasa a default `True`. Documentar en
`.env.example` que hay que ponerlo a `false` solo para desarrollo en
`http://localhost`. Opcional: renombrar la cookie a
`__Host-muxspace_session` (exige `Secure`, `path=/` y nada de `Domain`, que
es justo como ya se emite).

### 1.4 · `CORS_ORIGINS` con el mismo parser (S7)

`backend/config.py:121`:

```python
CORS_ORIGINS: list[str] = _get_str_list(
    "MUXSPACE_CORS_ORIGINS",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)
```

### 1.5 · Permisos de los datos (S9)

En el arranque de `main.py` (o en cada `_ensure_dir`): `data/` a `0o700`, y
`0o600` en los ficheros que escriben `library_store`, `space_store`,
`upload_store`, `auth` y las capturas.

---

## Fase 2 — Pruebas de backend

Base: `pytest`, `pytest-cov`, `httpx` (para `TestClient`) en un
`backend/requirements-dev.txt` aparte, para no engordar producción.

Estructura:

```
backend/tests/
├── conftest.py          # app con .env de prueba, tmpdir para data/, cliente
├── test_auth_contract.py
├── test_dir_roots.py
├── test_upload.py
├── test_auth.py
├── test_stores.py
└── test_tmux_service.py
```

`conftest.py` debe fijar las variables de entorno **antes** de importar
`config` (se leen en import time) y apuntar `DIR_SUGGESTION_ROOTS` y los
stores a un `tmp_path`, para que ninguna prueba toque los datos reales.

### 2.1 · Contrato de autenticación *(el más importante)*

```python
PUBLICAS = {"/api/health", "/api/login", "/api/logout"}

def test_toda_ruta_api_exige_auth():
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api"):
            if r.path in PUBLICAS:
                continue
            deps = [d.call.__name__ for d in r.dependant.dependencies]
            assert "require_auth" in deps, f"{r.path} sin autenticación"
```

Más un test que recorra las rutas reales con `TestClient` sin cookie y
exija 401, y otro para el WebSocket (cierre 1008).

### 2.2 · Raíces y traversal (`dir_suggestions`)

Casos: `../` explícito · symlink de directorio que apunta fuera ·
ruta absoluta fuera de raíz · `~` de otro usuario · raíz inexistente ·
`resolve_within_roots("")` → primera raíz · `create_dir` con `..` en el
nombre.

### 2.3 · Subida de archivos

Nombres inválidos (`../x`, `a/b`, `.`, `..`, vacío) · colisión → ` (2)` ·
**symlink colgante → 4xx y no escribe** (regresión de S3) · cuerpo por
encima del tope → 413 sin bufferizar (regresión de S4) · `dir` fuera de
raíces → 400 · historial recorta a `KEEP`.

### 2.4 · Autenticación

5 fallos/minuto → 429 · la ventana se resetea pasados 60 s · el registro
sobrevive a recargar el módulo (persistencia) · HTTP Basic incorrecto
penaliza igual · sesión expirada → 401 · `banned_ips.json` con CIDR bloquea
y se recarga en caliente al cambiar el mtime.

### 2.5 · Stores

CRUD de `library_store` y `space_store` · JSON corrupto → colección vacía
(no excepción) · escritura atómica (no queda `.tmp` suelto) · validaciones
(`err.command_empty`, `err.project_needs_command`, título > 60).

### 2.6 · `tmux_service`

Con tmux real (en CI: `apt-get install -y tmux`), sobre nombres con prefijo
propio y `kill` en el teardown: crear · duplicado → `False` · renombrar ·
matar · `_quote_path` con espacios, `$(...)`, `;` y `~`.

**Objetivo de cobertura**: 60% global de entrada; ≥85% en `auth.py`,
`dir_suggestions.py` y los endpoints de subida.

---

## Fase 3 — CI y linters

`.github/workflows/ci.yml`, dos jobs en paralelo, merge bloqueado:

```yaml
backend:   ruff check backend/  →  pytest --cov=backend --cov-fail-under=60
frontend:  bun install --frozen-lockfile  →  eslint  →  vitest run
           →  bun run build  →  bun run check-i18n
```

- `ruff` con la config en `pyproject.toml` (reglas `E,F,I,B,S` — `S` es
  `flake8-bandit`, apropiado aquí).
- `eslint` + `prettier` en el frontend, con script `lint` en
  `frontend/package.json` (hoy no existe).
- **`check-i18n` como error**: hoy solo avisa. Antes de activarlo, limpiar
  las 3 claves sin uso y decidir qué hacer con los plurales `many`
  (documentado en [`i18n.md`](i18n.md): el runtime cae a `other`, así que
  basta con silenciar ese aviso concreto).

---

## Fase 4 — Frontend

### 4.1 · Trocear `Sidebar.jsx` (2.572 líneas)

Prerrequisito práctico para poder testear. Extracción mecánica, un commit
por componente y sin cambios de comportamiento:

```
components/sidebar/PasteForClaude.jsx
components/sidebar/UploadFiles.jsx
components/sidebar/DirBrowserModal.jsx
components/sidebar/Modal.jsx
components/sidebar/CommandSelect.jsx
components/sidebar/SectionCaret.jsx
lib/paths.js          # quotePath
```

### 4.2 · Vitest

- `quotePath`: rutas limpias sin comillas · espacios → entrecomillado ·
  `"`, `$`, `` ` ``, `\` escapados · `~` sin comillas.
- Acordeón del sidebar: abrir una cierra las demás · volver a pulsar cierra
  · se persiste en `localStorage` y se restaura.
- `suggestName` (nombres `sesion-N` sin colisión).
- `api.js`: `ApiError` parsea `{code, params}` y cae al genérico con un
  `detail` de otra forma.

---

## Fase 5 — Observabilidad y deuda

- **Audit log (S8)**: `data/audit.log`, un JSON por línea
  `{ts, ip, user, action, target, detail}` en `send-command`, `launch`,
  `run-project`, `create/kill/rename-session` y `upload`. Rotación simple
  por tamaño.
- **`upload_store._save` atómico** (Q4): tmp + `replace`, como los otros
  tres stores.
- **`_ensure_tmux_server` una sola vez por proceso** (Q4): hoy son 2
  procesos cada 8 s por pestaña abierta.
- **Un solo worker**: documentarlo en el README (los locks son de proceso) o
  pasar a locking de fichero.
- **Sesiones (S10)**: TTL deslizante de 24 h + `POST /api/logout-all`.
- **`preexec_fn` (S11)**: migrar a `os.forkpty()` en `pty_bridge`. Es el
  cambio más delicado del plan (toca el camino del terminal): dejarlo para
  el final y con las pruebas ya en marcha.
- **i18n**: borrar `grid.layout_auto/cols/rows` y cerrar los avisos de
  plurales.

---

## Fase 6 — E2E (opcional)

Playwright, tres casos, contra el backend real con un `.env` de prueba:

1. login → listar sesiones → crear sesión.
2. abrir una terminal, escribir `echo hola` y ver el eco.
3. subir un archivo y comprobar que la ruta copiada es la esperada
   (entrecomillada si lleva espacios).

---

## Riesgos del propio plan

- **Fase 0.2 puede dejarte fuera del panel** si PAM no valida. Mitigación:
  probar el login por `curl` antes de cerrar la sesión del navegador, y
  tener a mano el fallback a `AUTH_MODE=env`.
- **La CSP puede romper el terminal o las miniaturas.** Mitigación:
  desplegar la Fase 0.1 mirando la consola del navegador; si algo falla, la
  directiva concreta se relaja (`connect-src`) sin tocar
  `frame-ancestors`, que es la que aporta la protección real.
- **Fase 4.1 toca el archivo más grande del proyecto.** Mitigación: commits
  por componente, sin cambios funcionales mezclados, y hacerlo *después* de
  la Fase 3 para tener el build y el lint verificando cada paso.
- **Fase 2 puede tocar datos reales** si `conftest.py` no aísla bien los
  paths. Mitigación: primer test del `conftest` que verifique que
  `_STORE_PATH` cae bajo `tmp_path`.

## Definition of Done (a partir de la Fase 3)

Un cambio está terminado cuando: tiene un test que falla sin él · `ruff` y
`eslint` limpios · `check-i18n` sin errores · build verde · README/docs
actualizados si cambia comportamiento observable · y, si toca autenticación,
rutas o ficheros, **un test de seguridad específico**.
