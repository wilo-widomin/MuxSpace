/**
 * El idioma de los mensajes de error sigue al que el usuario tiene puesto.
 *
 * Parece una perogrullada y era un bug. `App.jsx` memoizaba sus tres
 * cargadores con `useCallback(..., [])`, y dentro llaman a
 * `handleAuthFailure`, que traduce con `t`. Como `t` se recrea al cambiar de
 * idioma (`useMemo(..., [lang])` en `i18n/index.jsx`), aquellas dependencias
 * vacías dejaban capturado **el traductor del primer render para siempre**:
 * quien entrara en español y se pasara a inglés seguía viendo los errores en
 * español.
 *
 * Lo cazó `react-hooks/exhaustive-deps`, que llevaba avisando desde US-008
 * entre otros cuatro warnings que no eran bugs. Este test es para que, si
 * alguien vuelve a "limpiar" esas dependencias, se entere aquí y no en
 * producción.
 *
 * Se prueba por el camino del 401 porque es el único que enseña un mensaje
 * traducido **después** de haber podido cambiar de idioma: el resto de
 * errores se pintan y se van.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { T, entrar, expect, test } from './fixtures.js'

const AQUI = path.dirname(fileURLToPath(import.meta.url))

/** Los mismos textos, en inglés: es contra lo que se compara. */
const EN = JSON.parse(
  fs.readFileSync(path.join(AQUI, '..', 'src', 'i18n', 'locales', 'en.json'), 'utf8'),
)

test('tras cambiar de idioma, el aviso de sesión caducada sale en el nuevo', async ({
  page,
  context,
  entorno,
}) => {
  await entrar(page, entorno)

  // 1 · Cambiar a inglés. A partir de aquí el panel entero está en inglés.
  await page.getByLabel(T['lang.label']).selectOption('en')
  await expect(page.getByRole('button', { name: EN['sidebar.logout'] })).toBeVisible()

  // 2 · Caducar la sesión por detrás. Borrar la cookie es lo más parecido a
  //     que el servidor la haya invalidado: la siguiente petición sale 401.
  await context.clearCookies()

  // 3 · Forzar una petición. El sondeo lo haría solo en 8 s; pulsar
  //     "Refrescar" lo provoca ya y hace el test rápido y determinista.
  await page.getByRole('button', { name: EN['sidebar.refresh'] }).click()

  // 4 · Vuelve el login con el aviso... y tiene que estar EN INGLÉS.
  await expect(page.getByText(EN['app.session_expired'])).toBeVisible()
  await expect(page.getByText(T['app.session_expired'])).toHaveCount(0)
})
