/**
 * Conversaciones pasadas de Claude: búsqueda y estado «apagado».
 *
 * El API de sesiones (el de project-dashboard) NO se toca: el navegador solo
 * habla con el backend del panel, y aquí las respuestas de
 * `/api/claude-sessions…` se simulan con datos sintéticos en el propio
 * navegador. Lo que se comprueba es lo que solo se ve en un navegador de
 * verdad (con su CSP): que un fragmento con HTML sale como texto, que lo
 * marcado se resalta, que lo que parece una clave sale tapado y que el 503
 * enseña el mensaje y el comando del API tal cual.
 */
import { T, entrar, expect, test } from './fixtures.js'

const ID = '11111111-2222-3333-4444-555555555555'

test('la búsqueda pinta el fragmento como texto y tapa lo que parece una clave', async ({
  page,
  entorno,
}) => {
  await page.route('**/api/claude-sessions**', async (route) => {
    const req = route.request()
    if (req.method() === 'POST' && req.url().endsWith('/api/claude-sessions/search')) {
      // La consulta viaja en el cuerpo, nunca en la URL.
      expect(req.url()).not.toContain('claves')
      expect(req.postDataJSON().q).toBe('claves')
      return route.fulfill({
        json: {
          hits: [
            {
              session_id: ID,
              project: '/p/proyecto-de-prueba',
              title: 'Charla de prueba',
              role: 'user',
              kind: 'text',
              ts: '2026-11-27T13:51:42.448Z',
              agent_id: '',
              segments: [
                {
                  text: '<img src=x onerror="window.__xss=1"> ',
                  mark: false,
                  secret: false,
                },
                { text: 'claves', mark: true, secret: false },
                { text: ' ', mark: false, secret: false },
                { text: 'sk-sintetica1234567890abcdef', mark: false, secret: true },
              ],
            },
          ],
        },
      })
    }
    return route.fulfill({ json: { sessions: [] } })
  })

  await entrar(page, entorno)
  await page.getByRole('button', { name: T['csessions.open_global'] }).click()
  const caja = page.getByPlaceholder(T['csessions.search_placeholder'])
  await caja.fill('claves')
  await caja.press('Enter')

  const resultado = page.getByRole('listitem').filter({ hasText: 'Charla de prueba' })
  await expect(resultado).toBeVisible()
  await expect(resultado).toContainText('27/11/2026')
  await expect(resultado).toContainText('<img src=x onerror="window.__xss=1">')
  await expect(resultado.locator('img')).toHaveCount(0)
  expect(await page.evaluate(() => window.__xss)).toBeUndefined()
  await expect(resultado.locator('mark')).toHaveText('claves')

  await expect(resultado).not.toContainText('sk-sintetica1234567890abcdef')
  await resultado.getByRole('button', { name: T['csessions.show_secret'] }).click()
  await expect(resultado).toContainText('sk-sintetica1234567890abcdef')
})

test('con las sesiones apagadas se ve el mensaje y el comando, y nada más', async ({
  page,
  entorno,
}) => {
  await page.route('**/api/claude-sessions**', (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail: {
          code: 'err.claude_sessions_disabled',
          mensaje: 'Apagadas en el servidor.',
          detail: 'Para activarlas: touch /ruta/de/prueba',
        },
      },
    }),
  )
  await entrar(page, entorno)
  await page.getByRole('button', { name: T['csessions.open_global'] }).click()
  await page.getByRole('button', { name: T['csessions.tab_recent'] }).click()

  await expect(
    page.getByText('Apagadas en el servidor.', { exact: true }),
  ).toBeVisible()
  await expect(page.getByText('Para activarlas: touch /ruta/de/prueba')).toBeVisible()
})
