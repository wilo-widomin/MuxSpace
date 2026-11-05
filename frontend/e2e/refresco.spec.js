/**
 * Proyectos y espacios que cambian fuera de esta pestaña.
 *
 * El panel solo los cargaba al montar o tras una acción propia, así que lo que
 * creaba un script o se editaba en otro aparato no se veía hasta recargar.
 *
 * Lo que se afirma es lo que hay en el DOM y lo que escribió el usuario en el
 * formulario, no una captura. Los cambios se hacen con `fetch` directo: es la
 * misma API que usaría un script y no pasa por los manejadores de la pestaña.
 */
import { T, entrar, expect, test } from './fixtures.js'
import { PREFIJO_SESION } from './entorno.js'

const titulo = (sufijo) => `${PREFIJO_SESION}${Date.now().toString(36)}-${sufijo}`

/** Crea un proyecto saltándose la interfaz. Devuelve el proyecto creado. */
const crearFuera = (page, title) =>
  page.evaluate(async (t) => {
    const r = await fetch('/api/projects', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t, commands: ['true'] }),
    })
    return r.json()
  }, title)

const borrarFuera = (page, proyecto) =>
  page.evaluate(async ({ id, space }) => {
    const opciones = { method: 'DELETE', credentials: 'same-origin' }
    await fetch(`/api/projects/${id}`, opciones)
    await fetch(`/api/spaces/${space}`, opciones)
  }, proyecto)

// `visible`: el título sale también como `<option>` del selector de espacios de
// cada sesión, y un `<option>` de un `<select>` cerrado no se pinta.
const enLaLista = (page, title) =>
  page
    .locator('aside')
    .getByText(title, { exact: true })
    .filter({ visible: true })
    .first()

test('lo creado fuera aparece sin recargar y no borra lo que se está escribiendo', async ({
  page,
  entorno,
}) => {
  await entrar(page, entorno)

  await page.getByRole('button', { name: T['sidebar.new_project'] }).click()
  const campo = page.getByLabel(T['form.title_label'])
  await campo.fill('borrador a medias')

  const peticiones = []
  page.on('request', (r) => {
    if (r.method() === 'GET' && r.url().endsWith('/api/projects')) peticiones.push(r)
  })
  const nombre = titulo('fuera')
  const proyecto = await crearFuera(page, nombre)

  await expect(enLaLista(page, nombre)).toBeVisible()
  // El espacio que el alta creó con él ya está en el selector del formulario.
  await expect(
    page.locator('form select').last().getByRole('option', { name: nombre }),
  ).toHaveCount(1)

  await expect(campo).toHaveValue('borrador a medias')
  await expect(campo).toBeFocused()

  // Un cambio es una recarga: si recargar generara otro aviso, esto crecería.
  await page.waitForTimeout(1500)
  expect(peticiones).toHaveLength(1)

  await borrarFuera(page, proyecto)
  await expect(page.locator('aside').getByText(nombre, { exact: true })).toHaveCount(0)
})

test('lo que cambió con el bus cortado se recupera al reconectar', async ({
  page,
  entorno,
}) => {
  const conexiones = []
  await page.routeWebSocket('**/api/events', (ws) => {
    conexiones.push(ws)
    // La primera no llega al backend, así que no recibe ningún evento: es
    // igual que perderse el aviso. La segunda ya es la de verdad.
    if (conexiones.length > 1) ws.connectToServer()
  })
  await page.reload()
  await entrar(page, entorno)
  await expect.poll(() => conexiones.length).toBe(1)

  const nombre = titulo('perdido')
  const proyecto = await crearFuera(page, nombre)
  await page.waitForTimeout(600)
  await expect(page.locator('aside').getByText(nombre, { exact: true })).toHaveCount(0)

  await conexiones[0].close()

  await expect(enLaLista(page, nombre)).toBeVisible()
  expect(conexiones).toHaveLength(2)

  await borrarFuera(page, proyecto)
})
