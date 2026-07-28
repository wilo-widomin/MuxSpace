/**
 * Configuración de Playwright para los E2E del panel.
 *
 * Vive en `frontend/` y no en un `e2e/` de la raíz, y es una decisión: la
 * única cadena de herramientas JavaScript del repo está aquí
 * (`frontend/node_modules`, `bun.lock`, eslint, vitest). Un `e2e/` en la raíz
 * necesitaría su propio `package.json` y su propio `bun install`, duplicando
 * dependencias para no ganar nada. Que los tests arranquen un backend de
 * Python no lo convierte en un proyecto aparte: lo mismo hace el `dev.sh`.
 *
 * `baseURL` no se fija aquí porque el puerto se decide en el arranque (se pide
 * uno libre al sistema). Cada test lo lee de `entorno.json`.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',

  // El E2E levanta UN backend con UN servidor de tmux y crea sesiones reales
  // en él. Dos workers se pisarían las sesiones y el listado del sidebar
  // dejaría de ser determinista.
  workers: 1,
  fullyParallel: false,

  // Cero reintentos, aquí y en CI. Un test E2E que pasa al segundo intento
  // está roto: reintentar solo esconde cuánto.
  retries: 0,

  // Generosos porque hay un tmux de por medio, pero no infinitos: un test
  // colgado tiene que fallar, no dejar la suite esperando.
  timeout: 60_000,
  expect: { timeout: 10_000 },

  globalSetup: './e2e/global-setup.js',
  globalTeardown: './e2e/global-teardown.js',

  reporter: [['list']],

  use: {
    // El panel elige idioma por `navigator.language`. Sin fijarlo, Chromium
    // arranca en en-US y los tests afirmarían contra textos que no son los
    // que comprueban. Se fija en español, que es el idioma base del proyecto.
    locale: 'es-ES',
    // Solo cuando algo falla: en verde no interesan y ocupan.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
