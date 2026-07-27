# US-017 · Vitest: `quotePath`, acordeón, `suggestName` y `ApiError`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-4-frontend | S3 |

## Historia

Como responsable del panel, quiero **tests de frontend** sobre las cuatro
piezas de lógica que hoy solo se validan a ojo, para que el CI pueda
comprobar algo más que "compila".

## Criterios de aceptación

**Andamiaje**:

- [ ] `vitest` y `@testing-library/react` (+ `jsdom`) en `devDependencies`,
      instalados con **`bun add -d`**.
- [ ] Script `test` en `frontend/package.json`; `cd frontend && bun run test`
      corre en verde y `vitest run` sirve para CI.
- [ ] Entrada `test` añadida a `verify` en
      `.claude/us-pipeline.config.json`, en este mismo PR.

**`quotePath`** (de `lib/paths.js`, US-010):

- [ ] Ruta limpia (`/home/willy/proyecto`) → sin comillas.
- [ ] Ruta con espacios → entrecomillada.
- [ ] `"`, `$`, `` ` `` y `\` → escapados dentro de las comillas.
- [ ] `~` y `~/algo` → **sin** comillas (para que el shell lo expanda).
- [ ] Cadena vacía → comportamiento definido y probado.

**Acordeón del sidebar**:

- [ ] Abrir una sección **cierra las demás** (solo una abierta a la vez).
- [ ] Volver a pulsar sobre la abierta la cierra.
- [ ] La sección abierta se persiste en `localStorage`
      (clave `muxspace-sidebar-section`).
- [ ] Al montar de nuevo, se **restaura** la sección guardada.
- [ ] Un valor basura en `localStorage` no rompe el render.

**`suggestName`**:

- [ ] Sin sesiones → `sesion-1`.
- [ ] Con `sesion-1` y `sesion-2` ocupados → `sesion-3`.
- [ ] Con huecos (`sesion-1`, `sesion-3`) → devuelve un nombre libre y
      **nunca uno ocupado**.

**`ApiError` (`api.js`)**:

- [ ] Un `detail` con forma `{code, params}` se parsea: `err.code` y
      `err.params` quedan poblados.
- [ ] Un `detail` que es una cadena → cae al genérico sin `code`.
- [ ] Un 401 produce `err.unauthorized`.
- [ ] Un cuerpo que no es JSON → `err.http` con el `status` en `params`.
- [ ] `technical` se conserva cuando viene.

## Alcance técnico

- `frontend/vitest.config.js` (o la sección `test` de `vite.config.js`),
  con entorno `jsdom`.
- `frontend/src/lib/paths.test.js`
- `frontend/src/api.test.js`
- `frontend/src/components/Sidebar.test.jsx` (acordeón y `suggestName`)
- `frontend/package.json`, `frontend/bun.lock`

Para el acordeón necesitarás mockear `api.js` (el sidebar carga comandos,
proyectos y espacios al montar) y limpiar `localStorage` entre tests.

Si `suggestName` no está exportada, expórtala: es un cambio de una palabra y
es la forma honesta de testearla, mejor que llegar a ella por el DOM.

## Fuera de alcance

- Tests de los componentes extraídos (`UploadFiles`, `PasteForClaude`…): el
  plan pide estas cuatro piezas y ninguna más.
- Tests de `XtermTerminal` o del WebSocket: eso es E2E (fase 6).
- Snapshot testing.

## Dependencias

US-010, US-016.

## Rigor

`estándar`.

## Concurrencia

`compartida` una vez terminadas las extracciones; por eso va en el sprint
S3, detrás de todas ellas.

## Notas para el agente

- El test del acordeón es el que más valor tiene: la persistencia en
  `localStorage` es justo lo que se rompe sin que nadie se entere hasta que
  molesta.
- Un test de frontend que necesite `waitFor` de segundos está mal montado:
  mockea `api.js`, no esperes a la red.
