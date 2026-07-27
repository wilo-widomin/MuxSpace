# Backlog de historias de usuario

26 historias que ejecutan las **fases 2 a 6** de
[`../plans/seguridad-y-qa.md`](../plans/seguridad-y-qa.md). Las fases 0 y 1
(las correcciones de seguridad) se hicieron a mano; ver PR #1.

Antes de tocar nada: [`contexto-tecnico.md`](contexto-tecnico.md). Contiene
las reglas del proyecto y el
[Definition of Done](contexto-tecnico.md#definition-of-done).

Las procesa la skill `us-pipeline` con la configuración de
[`../../.claude/us-pipeline.config.json`](../../.claude/us-pipeline.config.json):
una rama + worktree + PR por historia.

## Orden de ejecución

El pipeline ordena por fase → sprint → prioridad → número, y difiere lo que
tenga dependencias sin mergear.

### Fase 2 · Pruebas de backend

| US | Puntos | Deps | Qué hace |
|---|---|---|---|
| [US-001](fase-2-tests/US-001-andamiaje-de-pytest-aislado.md) | 3 | — | Andamiaje de pytest **aislado de `backend/data/`** |
| [US-002](fase-2-tests/US-002-contrato-de-autenticacion.md) | 3 | 001 | Contrato de autenticación sobre `app.routes` |
| [US-003](fase-2-tests/US-003-raices-y-traversal.md) | 3 | 001 | Raíces y traversal en `dir_suggestions` |
| [US-004](fase-2-tests/US-004-subida-de-archivos.md) | 5 | 001 | Subida: regresiones de **S3** (symlink) y **S4** (tamaño) |
| [US-005](fase-2-tests/US-005-autenticacion-rate-limit-y-baneos.md) | 5 | 001 | Rate limit, sesiones y baneos por CIDR |
| [US-006](fase-2-tests/US-006-stores.md) | 3 | 001 | Stores: CRUD, JSON corrupto, escritura atómica |
| [US-007](fase-2-tests/US-007-tmux-service.md) | 3 | 001 | `tmux_service` contra tmux real |

### Fase 3 · CI y linters

| US | Puntos | Deps | Qué hace |
|---|---|---|---|
| [US-008](fase-3-ci/US-008-linters.md) | 3 | 001 | `ruff` + `eslint` + `prettier` |
| [US-022](fase-3-ci/US-022-i18n-claves-y-plurales.md) | 1 | — | Dejar `check-i18n` sin avisos |
| [US-009](fase-3-ci/US-009-workflow-de-ci.md) | 3 | 001, 008, 022 | Workflow de CI bloqueante |

US-022 vive aquí, y no en la fase 5 como decía el plan, porque US-009 no
puede activar `check-i18n` como error mientras el script escupa avisos.

### Fase 4 · Frontend

Las siete extracciones son **movimientos mecánicos, sin cambios de
comportamiento**, y todas son exclusivas: tocan el mismo `Sidebar.jsx`.

| US | Puntos | Deps | Qué hace |
|---|---|---|---|
| [US-010](fase-4-frontend/US-010-extraer-quotepath-a-lib-paths.md) | 1 | — | `quotePath` → `lib/paths.js` |
| [US-011](fase-4-frontend/US-011-extraer-modal.md) | 1 | — | `Modal` |
| [US-012](fase-4-frontend/US-012-extraer-sectioncaret.md) | 1 | — | `SectionCaret` |
| [US-013](fase-4-frontend/US-013-extraer-commandselect.md) | 1 | — | `CommandSelect` |
| [US-014](fase-4-frontend/US-014-extraer-dirbrowsermodal.md) | 2 | 011 | `DirBrowserModal` |
| [US-015](fase-4-frontend/US-015-extraer-uploadfiles.md) | 3 | 010, 012, 014 | `UploadFiles` |
| [US-016](fase-4-frontend/US-016-extraer-pasteforclaude.md) | 3 | 010, 012 | `PasteForClaude` |
| [US-017](fase-4-frontend/US-017-vitest.md) | 3 | 010, 016 | Vitest: `quotePath`, acordeón, `suggestName`, `ApiError` |

Objetivo medible: `Sidebar.jsx` baja de **2.572 a menos de 1.700 líneas**.

### Fase 5 · Observabilidad y deuda

| US | Puntos | Deps | Qué hace |
|---|---|---|---|
| [US-018](fase-5-deuda/US-018-audit-log.md) | 3 | 001 | Audit log JSONL (**S8**) |
| [US-019](fase-5-deuda/US-019-polling-de-tmux.md) | 2 | 007 | `start-server` una vez por proceso |
| [US-020](fase-5-deuda/US-020-sesiones-ttl-deslizante-y-logout-all.md) | 3 | 005 | TTL deslizante + `logout-all` (**S10**) |
| [US-023](fase-5-deuda/US-023-documentar-un-solo-worker.md) | 1 | — | Documentar el requisito de un solo worker |
| [US-021](fase-5-deuda/US-021-forkpty.md) | 3 | 001, 007 | `os.forkpty()` (**S11**) — el más delicado, va el último |

El punto "`upload_store._save` atómico" del plan **ya no tiene trabajo**: cayó
al centralizar el tmp + replace en `datafiles.write_private` (PR #1).

### Fase 6 · E2E (opcional)

| US | Puntos | Deps | Qué hace |
|---|---|---|---|
| [US-024](fase-6-e2e/US-024-e2e-login-listar-y-crear-sesion.md) | 5 | 009 | Login → listar → crear sesión (+ andamiaje de Playwright) |
| [US-025](fase-6-e2e/US-025-e2e-terminal-con-eco.md) | 3 | 024 | Abrir terminal y ver el eco |
| [US-026](fase-6-e2e/US-026-e2e-subida-y-ruta-copiada.md) | 3 | 024 | Subir archivo y comprobar la ruta copiada |

## Regla que atraviesa todo el backlog

Las US de la fase 2 **no arreglan código**: levantan la red sobre lo que ya
se corrigió. Si un test encuentra que algo falla de verdad, eso es un
**hallazgo de seguridad**, no un arreglo que se cuela en el PR de un test.
Se para y se avisa.
