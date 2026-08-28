---
actualizado: 2026-08-28
archivos:
  - backend/main.py
  - backend/config.py
  - backend/datafiles.py
  - frontend/package.json
  - pyproject.toml
  - .github/workflows/ci.yml
  - start.sh
  - scripts/dev.sh
---

# Arquitectura

Panel web que gestiona el servidor de tmux del usuario que ejecuta el backend.
`send-command`, `launch`, `run-project` y el WebSocket del PTY **ejecutan
comandos arbitrarios** como ese usuario: no hay sandbox ni lista blanca. De ahí
el criterio que ordena todo: el control de acceso es el 100 % del perímetro, y
un fallo que permita provocar una acción desde otra pestaña equivale a
ejecución remota de código.
## Stack

- **Backend**: FastAPI + uvicorn, Python 3.11. Un módulo por responsabilidad,
  sin capas ni paquete instalable: se importan en plano (`import config`),
  porque uvicorn arranca con `--app-dir backend`.
- **Frontend**: React 18 + Vite + Tailwind, sin router (la vista se decide con
  `window.location.pathname` en `frontend/src/App.jsx`). Terminal propia con
  `@xterm/xterm`.
- **Extensión** de Chrome (MV3) en `extension/`, paquete aparte con su lockfile.
- **Persistencia**: archivos bajo `backend/data/` (JSON y una SQLite para la
  jornada). Sin base de datos de servidor ni ORM.

## Capas

`frontend/src/api.js` → middlewares de `backend/main.py` (no-cache, guard de
Origin, baneo de IP, cabeceras) → endpoint → módulo de dominio (`tmux_service`,
`library_store`, `space_store`, `upload_store`, `worklog`) →
`backend/datafiles.py` (0600, tmp + replace). El backend sirve además
`frontend/dist` ya compilado.

## Convenciones

- **`bun`, nunca `npm` ni `npx`** — instalar, ejecutar scripts, añadir
  dependencias. El lockfile es `frontend/bun.lock`.
- **Los errores son claves i18n, no frases**: `http_error(400, "err.x")` y la
  traducción vive en los 6 catálogos (ver `i18n/`).
- **tmux siempre por `argv`**, nunca por shell.
- **Un solo worker de uvicorn**: los locks de los stores son de proceso; con
  varios se corrompe la biblioteca (`docs/un-solo-worker.md`).
- `backend/config.py` lee el entorno **en import time**: fijar variables
  después de importar no cambia nada, y recargar exige `importlib.reload`.
- Código en inglés; comentarios y documentación en español. Rama + PR siempre.

## Arrancar y probar

```bash
./start.sh                 # producción (backend + dist)   ·  scripts/dev.sh en caliente
cd frontend && bun run build          # obligatorio tras tocar el frontend
backend/venv/bin/python -m pytest -q
backend/venv/bin/python -m ruff check backend/
cd frontend && bun run lint && bun run format:check && bun run test
cd frontend && bun run check-i18n && bun run test:e2e
```

El gate de CI (`.github/workflows/ci.yml`) corre eso mismo en cuatro jobs
—backend, frontend, extension, e2e— con `--cov-fail-under=80` y tmux real: lo
que no se pueda reproducir en local no entra en el gate.

## Trampas

- **`backend/data/` son datos reales del usuario.** Ninguna prueba escribe ahí:
  `conftest.py` aísla los stores en `tmp_path` y su primer test lo verifica.
- **El backend en 127.0.0.1:8000 es el panel vivo del usuario**, con terminales
  abiertas. Las sesiones de tmux sobreviven a un reinicio; los WebSocket no.
  Pregunta antes de reiniciarlo; para probar, levanta una copia con su `data/`.
- El backend sirve `frontend/dist`: sin `bun run build` se ve lo de antes.
- `kill-server` de tmux es asíncrono: vuelve cuando ha mandado la orden, no
  cuando el servidor ha muerto. Encadenar `kill-server` + `new-session` falla
  ~6 % de las veces; el andamiaje de tests espera de verdad.
