---
dominio: acceso
accion: login-y-sesion
actualizado: 2026-08-28
archivos:
  - backend/auth.py
  - backend/main.py
  - backend/config.py
  - backend/.env.example
  - frontend/src/App.jsx
depende_de: [i18n/_dominio]
---

# Login y sesión

## Variables de entorno

| Variable | Por defecto | Si falta o está mal |
|---|---|---|
| `MUXSPACE_AUTH_ENABLED` | true | con `false`, todo el mundo es `anonymous` |
| `MUXSPACE_AUTH_MODE` | `env` | un valor desconocido impide arrancar |
| `MUXSPACE_USERNAME` / `MUXSPACE_PASSWORD` | `admin` / — | vacía o `admin` impide arrancar (modo `env`) |
| `MUXSPACE_PAM_SERVICE` | `login` | — |
| `MUXSPACE_SESSION_TTL_HOURS` / `_IDLE_HOURS` | 168 / 24 | — |
| `MUXSPACE_COOKIE_SECURE` | true | en dev sobre http hay que ponerla a false, o el navegador descarta la cookie y el login «no funciona» sin error visible |
| `MUXSPACE_CORS_ORIGINS` | — | alimenta CORS **y** el guard de Origin y el del WebSocket: un dominio que falte da 403 en todo POST y 1008 en el terminal |
| `MUXSPACE_TRUSTED_PROXIES` | 127.0.0.1 | la consume `start.sh`; con el proxy en otra máquina y sin añadirla, todas las IPs son la del proxy y 5 fallos bloquean a todos |
| `MUXSPACE_DOCS_ENABLED` | false | si se activa, `/docs` se sirve **sin auth** |

`backend/config.py` las lee **en import time**.

## Rate-limit y baneos

- 5 fallos por ventana de 60 s y por IP → 429 `err.login_rate_limited`. Aplica
  también al Basic. No es bloqueo progresivo: la ventana caduca sola.
- Se persiste en `backend/data/login_failures.json` (máx. 1000 IPs, se
  descartan las más antiguas). Un login correcto pone el contador a cero pero
  **conserva el histórico**.
- Baneos en `backend/data/banned_ips.json`: lista de IPs o CIDR, recargada por
  mtime. **Levantar un baneo = quitar la entrada y guardar.** Un JSON corrupto
  conserva la lista anterior.

## Auditoría

`backend/data/audit.log`, JSONL, 0600, rotación a `.1` a los 5 MB (solo una).
Cada línea: `ts` (ISO UTC), `ip`, `user`, `action`, `target`, `detail`.
Acciones: `login`, `login-failed`, `logout-all`, `create-session`,
`spawn-terminal`, `kill-session`, `rename-session`, `send-command`, `launch`,
`run-project`, `upload`. Nunca contraseñas ni tokens; un fallo al escribir no
tumba la petición.

## Trampas

- El 401 no lleva `WWW-Authenticate`, a propósito: dispararía el diálogo nativo
  del navegador.
- Cualquier 401 en los cargadores del frontend cierra la sesión de la interfaz
  y avisa con `app.session_expired`.
