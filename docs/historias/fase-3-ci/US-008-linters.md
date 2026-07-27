# US-008 · Linters: `ruff` en el backend, `eslint` + `prettier` en el frontend

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-3-ci | S1 |

## Historia

Como responsable del panel, quiero **linters configurados y en verde**, para
que el CI de US-009 tenga algo que ejecutar y para que dejen de colarse cosas
como el `HTTPException` importado y sin usar que la auditoría encontró a
simple vista en `backend/main.py`.

Esta US **no reescribe el código**: configura las herramientas, arregla lo
que salga y deja `lint` como un comando que existe.

## Criterios de aceptación

**Backend**:

- [ ] `ruff` en `backend/requirements-dev.txt`, con la configuración en el
      `pyproject.toml` de la raíz.
- [ ] Reglas activadas: `E`, `F`, `I`, `B` y **`S`** (`flake8-bandit`) —
      apropiado en un proyecto que ejecuta comandos.
- [ ] `backend/venv/bin/python -m ruff check backend/` termina **sin
      hallazgos**.
- [ ] Las reglas de `S` que haya que silenciar (por ejemplo, `subprocess`
      con `argv`, que aquí es la forma **correcta** de invocar tmux) se
      silencian con `# noqa: SXXX` **puntual y comentado**, nunca
      desactivando la regla entera en la config.
- [ ] `backend/venv/` y `backend/tests/` quedan excluidos o con las
      excepciones que necesiten (los tests usan `assert`, que `S101`
      penaliza).
- [ ] Los arreglos son **mecánicos**: imports muertos, variables sin usar,
      orden de imports. Cualquier cambio que altere comportamiento se saca
      del PR y se anota como hallazgo.

**Frontend**:

- [ ] `eslint` y `prettier` en `devDependencies`, instalados con **`bun`**
      (`bun add -d`), nunca con npm.
- [ ] Configuración de eslint para React + hooks (`react-hooks/rules-of-hooks`
      y `exhaustive-deps` activas), sin `eslint-config-airbnb` ni preajustes
      pesados: el proyecto es pequeño.
- [ ] Script `lint` en `frontend/package.json`: `cd frontend && bun run lint`
      funciona y termina sin errores.
- [ ] Script `format` (o `lint:fix`) documentado en el README.
- [ ] `prettier` con una configuración que **respete el estilo actual** del
      repo (sin punto y coma, comillas simples): el diff de formateo tiene
      que ser pequeño. Si sale enorme, ajusta la config, no el código.
- [ ] `bun run build` sigue verde y `bun run check-i18n` no pierde claves.

**Cierre**:

- [ ] `verify` de `.claude/us-pipeline.config.json` gana las dos entradas
      (`lint` de backend y de frontend) en este mismo PR.
- [ ] El README documenta cómo pasar los linters.

## Alcance técnico

Archivos a crear/tocar:

- `pyproject.toml` (sección `[tool.ruff]`).
- `backend/requirements-dev.txt`.
- `frontend/package.json`, `frontend/bun.lock`.
- `frontend/eslint.config.js` (flat config) y `frontend/.prettierrc`.
- `README.md`.
- Los archivos que los linters obliguen a tocar.

## Fuera de alcance

- El workflow de CI (US-009).
- Trocear `Sidebar.jsx` (fase 4). Si eslint se queja de complejidad ahí,
  silencia esa regla concreta con un comentario que apunte a la fase 4; no
  refactorices.
- Cualquier cambio de comportamiento.

## Dependencias

US-001.

## Rigor

`ligero`. Es tooling: el riesgo está en colar un cambio funcional
disfrazado de arreglo de lint.

## Concurrencia

`exclusiva`. Toca archivos de todo el repo; cualquier otra US en paralelo
choca.

## Notas para el agente

- Regla de oro: **si un arreglo de lint cambia lo que el programa hace, no
  es un arreglo de lint**. Sácalo del PR y anótalo.
- El lockfile cambia al añadir dependencias: commitéalo.
- `bun`, nunca `npm` ni `npx`. También para ejecutar eslint: `bunx eslint`.
