---
dominio: acceso
accion: apagar-host
actualizado: 2026-11-12
archivos:
  - backend/host_poweroff.py
  - backend/main.py
  - backend/config.py
  - backend/.env.example
  - host-agent/host_agent.py
  - host-agent/install.sh
  - host-agent/uninstall.sh
  - host-agent/muxspace-host-agent.service
  - frontend/src/components/HostPoweroffDialog.jsx
  - frontend/src/components/SettingsMenu.jsx
  - backend/tests/test_host_poweroff.py
  - backend/tests/test_host_agent.py
  - docs/apagar-host.md
depende_de: [acceso/_dominio, i18n/_dominio]
---

# Apagar el host

Desde Ajustes, una persona con sesión puede apagar el ordenador donde corre la
VM del panel. Documentación para humanos y pasos de instalación:
`docs/apagar-host.md`.

## Piezas

- **Agente del host** (`host-agent/`): servidor HTTP de la librería estándar que
  solo acepta `POST /poweroff` con `Authorization: Bearer`. Orden de las
  comprobaciones: origen permitido (403), método (405), ruta (404), token (401).
  Compara huellas SHA-256 con `hmac.compare_digest`, lee el token del archivo en
  cada petición (rotar no pide reinicio) y se niega a arrancar si el archivo no es
  del propietario y 600. La orden de apagado y la espera se inyectan solo en
  tests (`make_server(poweroff=…, delay=…)`).
- **Cliente** (`backend/host_poweroff.py`): `send()` hace el POST con timeout de
  5 s, sin seguir redirecciones (llevarían el token a otro sitio). `enabled()` es
  verdadero solo con `MUXSPACE_HOST_POWEROFF_URL` **y** `_TOKEN`.
- `GET /api/capabilities` → `{host_poweroff, host_poweroff_word}`; el frontend
  esconde la fila si es falso o si la consulta falla.
- `POST /api/host/poweroff` con `{confirmation}`: 404 `err.host_poweroff_disabled`,
  400 `err.host_poweroff_confirmation`, 502 `…_unreachable` / `…_rejected`, 200 si
  el agente aceptó.

## Invariantes

- **Solo sesión de persona.** La ruta declara `require_auth` y no `_script_auth`:
  el token de scripts no la abre, y hay un test con un token válido desde loopback.
  No está en las listas enumeradas de `test_auth_contract.py`.
- **La palabra de confirmación vive en el backend** (`CONFIRMATION_WORD`) y viaja
  por `/api/capabilities`; el frontend no la copia. Se compara sin distinguir
  mayúsculas porque los teclados de tableta las alteran.
- **Cada intento se audita** con acción `host-poweroff` y `detail.result`
  (`accepted`, `disabled`, `bad-confirmation`, `unreachable`, `rejected`). Nunca
  el token.
- La dirección y el token del host son de la red de Willy: solo en `backend/.env`,
  nunca en el repositorio.

## Trampas

- Los tests fijan las dos variables a vacío en `conftest.py`; un test que quiera la
  función habilitada fija `config` y sustituye `host_poweroff.send`.
- Un 202 del agente significa «lo apagaré en ~2 s», no «está apagado»: tras él el
  panel puede dejar de responder, y es lo esperado.
