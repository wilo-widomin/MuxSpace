# US-009 · Workflow de CI bloqueante

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-3-ci | S2 |

## Historia

Como responsable del panel, quiero **que no se pueda mergear con los tests o
los linters en rojo**, porque todo lo construido en las fases 1 y 2 se
deshace solo en cuanto deja de comprobarse.

Hoy lo único automático del proyecto es `check-i18n`, y no está enganchado a
ningún gate.

## Criterios de aceptación

- [ ] `.github/workflows/ci.yml` con **dos jobs en paralelo**, `backend` y
      `frontend`, disparados en `pull_request` y en `push` a `main`.
- [ ] Job **backend**: instala `requirements.txt` + `requirements-dev.txt`,
      instala **tmux** (`apt-get install -y tmux`, lo necesita US-007) y
      ejecuta `ruff check backend/` y luego
      `pytest --cov=backend --cov-fail-under=60`.
- [ ] Job **frontend**: `bun install --frozen-lockfile` → `lint` → `vitest
      run` → `bun run build` → `bun run check-i18n`.
- [ ] Se usa `oven-sh/setup-bun`, **nunca** `setup-node` con npm.
- [ ] `check-i18n` corre **como error, no como aviso**: si faltan claves o
      hay claves sin usar, el job falla. Requiere que US-022 haya limpiado
      antes las 3 claves muertas y cerrado los avisos de plurales — si aún
      no está hecho, esta US **se queda esperando**, no relaja el gate.
- [ ] Si `vitest` todavía no existe (US-017 sin mergear), ese paso se omite
      con una condición explícita y un comentario que diga qué US lo activa.
      Ningún paso "que pasa siempre" disfrazado de comprobación.
- [ ] Los dos jobs cachean dependencias (pip y bun) para que el CI no tarde
      minutos en cada push.
- [ ] Documentado en el README qué comprueba el CI y cómo reproducirlo en
      local.
- [ ] **Comprobado que muerde**: un commit con un test roto pone el CI en
      rojo. Deja constancia en el PR.
- [ ] La protección de rama en GitHub (checks obligatorios) queda
      documentada en el PR como paso manual para el dueño del repo: la
      configura él, no el pipeline.

## Alcance técnico

- `.github/workflows/ci.yml`.
- `README.md`.
- La cobertura mínima arranca en **60% global**. Los objetivos por módulo de
  la fase 2 (≥85% en `auth.py`, `dir_suggestions.py` y los endpoints de
  subida) se documentan pero **no** se imponen todavía como gate.

## Fuera de alcance

- Crear los linters (US-008) o los tests (fase 2).
- Despliegue automático. El panel se despliega a mano y así se queda.
- Publicar informes de cobertura en servicios externos.

## Dependencias

US-001, US-008, US-022.

## Rigor

`estándar`.

## Concurrencia

`compartida`. Solo crea el workflow y toca el README.

## Notas para el agente

- Un CI que nunca falla no es un CI. El criterio de "comprobado que muerde"
  es el que separa esta US de un archivo YAML decorativo.
- `--cov-fail-under=60` con la fase 2 mergeada debería pasar holgado. Si no
  llega, **no bajes el número**: dilo en el PR, es información sobre la
  cobertura real.
- Que el job de backend instale tmux es lo que permite que US-007 no se
  quede en `skip` permanente y nadie se entere.
