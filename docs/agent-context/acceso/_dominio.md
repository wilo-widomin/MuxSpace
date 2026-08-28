---
dominio: acceso
actualizado: 2026-08-28
archivos:
  - backend/auth.py
  - backend/audit.py
  - backend/config.py
  - backend/errors.py
  - backend/logs.py
  - backend/main.py
  - frontend/src/components/LoginScreen.jsx
  - frontend/src/api.js
  - docs/mtls.md
depende_de: [i18n/_dominio]
---

# Acceso

Controla quién entra (sesión en cookie, o HTTP Basic para la CLI) y protege la
puerta: rate-limit por IP, lista negra, guard de Origin, cabeceras de seguridad
y auditoría. Delante hay **mTLS terminado en un proxy externo**, que el backend
ni ve ni valida.

## Cómo se autentica

- `POST /api/login`. En modo `env` compara con `secrets.compare_digest`; en
  modo `pam` autentica contra PAM y **solo** si el usuario coincide con el que
  ejecuta el proceso.
- Sesión: token aleatorio en un dict **en memoria**. Reiniciar el backend echa
  a todo el mundo.
- Dos relojes por sesión: un tope absoluto fijado al entrar (168 h, no se
  renueva) y una ventana de inactividad (24 h, que sí se renueva en cada uso).
  Muere con el primero que venza.
- Cookie `muxspace_session`: `HttpOnly`, `SameSite=Lax`, `Secure` configurable.
  El `max_age` lleva el tope absoluto, pero la caducidad real la decide el
  servidor.
- El WebSocket usa **esa misma cookie del handshake**; no se acepta token en la
  URL.

## Invariantes

- Con `AUTH_ENABLED=false` el único control anti-CSRF que queda es el guard de
  Origin: configurar mal `CORS_ORIGINS` abre POSTs desde otro sitio contra un
  panel que da shell.
- El backend arranca o no arranca: un `AUTH_MODE` desconocido, o una contraseña
  vacía o `admin` en modo `env`, es `ValueError` al importar la configuración.
- Los errores viajan como `{code, params, technical}`, nunca como frase.

## Acciones documentadas

- [Login y sesión](login-y-sesion.md)
- [Cabeceras y CSP](cabeceras-y-csp.md)

## Trampas

- **Un solo worker, obligatorio**: las sesiones y los contadores viven en el
  proceso. Con varios, un login contra uno da 401 en el otro y el rate-limit
  permite N×5 intentos.
- Asimetría fácil de confundir: la lista de baneos **se recarga en caliente**
  por mtime; el registro de fallos de login se lee **solo al importar**, así
  que editarlo con el backend vivo no hace nada.
- Los 403 de baneo y de Origin devuelven `detail` como **string**, no como
  `{code}`: el frontend los pinta con el mensaje genérico.
- El WebSocket cierra siempre con 1008 sin motivo: depurar «no abre el
  terminal» obliga a descartar a mano baneo, Origin, cookie y sesión.
- `POST /api/logout-all` revoca también la sesión de quien llama, exige auth y
  no está en la interfaz: solo por curl.
- `logout` no se audita; las lecturas tampoco.
