# US-024 · E2E: login → listar sesiones → crear sesión

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 5 | fase-6-e2e | S1 |

## Historia

Como responsable del panel, quiero **un E2E que recorra el camino de entrada
completo**, porque es el único que prueba que el login, la cookie, el
listado y la creación de sesiones encajan de verdad en un navegador — con la
CSP de la fase 0 puesta.

Esta US trae además el andamiaje de Playwright del que dependen US-025 y
US-026.

## Criterios de aceptación

**Andamiaje** (solo en esta US):

- [ ] Playwright instalado con **`bun`** y configurado en
      `frontend/playwright.config.js` (o en `e2e/` en la raíz; decide y
      justifica).
- [ ] Un script arranca el backend con un **`.env` de prueba**: su propio
      `data/` en un directorio temporal, `MUXSPACE_AUTH_MODE=env` con una
      contraseña generada, y un puerto libre que **no sea el 8000**.
- [ ] El teardown para el backend y borra su directorio temporal.
- [ ] **Ninguna prueba toca `backend/data/`, el `.env` real ni el proceso de
      producción.** Es la regla que no se salta ni para depurar.
- [ ] Script `test:e2e` en `frontend/package.json`; documentado en el README.
- [ ] Las sesiones de tmux que cree el E2E llevan un prefijo propio y el
      teardown mata **solo** esas.

**El caso**:

- [ ] Sin sesión, la aplicación muestra la pantalla de login.
- [ ] Con credenciales incorrectas, aparece el mensaje de error traducido
      (no un texto en crudo del backend).
- [ ] Con credenciales correctas se entra, y la cookie de sesión llega con
      `HttpOnly`.
- [ ] El sidebar lista las sesiones de tmux existentes.
- [ ] Crear una sesión desde el panel la hace aparecer en el listado **y**
      existe de verdad en tmux (compruébalo con `tmux has-session`, no solo
      en el DOM).
- [ ] Crear una sesión con un nombre ya usado muestra el error traducido.
- [ ] **La consola del navegador no tiene ningún error de CSP** durante todo
      el recorrido. Es la comprobación que la fase 0 dejó pendiente de
      automatizar.

## Alcance técnico

- `e2e/` (o `frontend/e2e/`) con la config y los tests.
- Script de arranque/parada del backend de pruebas.
- `frontend/package.json`, `README.md`.

El frontend se sirve desde el build (`bun run build` + el `StaticFiles` del
backend), no desde el dev server: así se prueba **el mismo montaje que
producción**, incluidas las cabeceras de seguridad.

## Fuera de alcance

- Enganchar el E2E al CI. Necesita tmux y un navegador; se decide después,
  con datos de cuánto tarda.
- Los otros dos casos (US-025 y US-026).
- Probar el modo PAM: en pruebas se usa `AUTH_MODE=env`.

## Dependencias

US-009.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`. Levanta un backend y crea sesiones de tmux reales.

## Notas para el agente

- La fase 6 está marcada como **opcional** en el plan. Si el andamiaje se
  complica más de la cuenta, di que se complica en vez de dejar un E2E
  frágil: un test que falla aleatoriamente es peor que ninguno.
- La comprobación de la consola sin errores de CSP es, ella sola, media
  justificación de esta US.
