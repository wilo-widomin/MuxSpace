/**
 * E2E: login → listar sesiones → crear sesión (US-024).
 *
 * Es el camino de entrada completo, en un navegador de verdad, contra el
 * **build** servido por el `StaticFiles` del backend: el mismo montaje que
 * producción, con la CSP y las cabeceras de seguridad puestas. Nada de esto
 * se puede probar con vitest ni con el TestClient de FastAPI.
 *
 * Lo que se afirma aquí y en ningún otro sitio:
 *   - Que el login, la cookie `HttpOnly` y el listado encajan en un navegador.
 *   - Que crear una sesión desde el panel crea una sesión **en tmux**, no solo
 *     un `<li>` en el DOM.
 *   - Que el recorrido entero no dispara ni una violación de CSP.
 */
import { PREFIJO_SESION } from './entorno.js'
import {
  T,
  campoPassword,
  campoUsuario,
  entrar,
  expect,
  nombreSesion,
  sesionEnLista,
  test,
} from './fixtures.js'

/**
 * El campo "nombre de la nueva sesión" del modal.
 *
 * Solo lo usa este spec, así que se queda aquí y no en las fixtures: es el
 * primer `input` de texto del formulario del modal.
 */
const campoNombreSesion = (page) =>
  page.locator('form input[type="text"], form input:not([type])').first()

test('sin sesión, el panel muestra la pantalla de login', async ({ page }) => {
  await expect(page.getByText(T['login.subtitle'])).toBeVisible()
  await expect(page.getByRole('button', { name: T['login.submit'] })).toBeVisible()
  // Y no se cuela nada del panel: si el sidebar se pintara antes de saber si
  // hay sesión, se vería un instante la lista de terminales del usuario.
  await expect(
    page.getByRole('button', { name: T['sidebar.logout'] }),
  ).toHaveCount(0)
})

test('con credenciales incorrectas sale el mensaje traducido', async ({
  page,
  entorno,
}) => {
  await campoUsuario(page).fill(entorno.usuario)
  await campoPassword(page).fill('esta-no-es')
  await page.getByRole('button', { name: T['login.submit'] }).click()

  // El texto traducido, no el `detail` en crudo del backend: lo que el
  // usuario debe ver es "Usuario o contraseña incorrectos", no
  // "err.bad_credentials" ni un 401 sin más.
  await expect(page.getByText(T['err.bad_credentials'])).toBeVisible()
  await expect(page.getByText('err.bad_credentials')).toHaveCount(0)
  await expect(page.getByText('401')).toHaveCount(0)
})

test('con credenciales correctas se entra y la cookie es HttpOnly', async ({
  page,
  context,
  entorno,
}) => {
  await entrar(page, entorno)

  const cookies = await context.cookies()
  const sesion = cookies.find((c) => c.name === 'muxspace_session')
  expect(sesion, 'no llegó la cookie de sesión').toBeTruthy()
  // `HttpOnly` es lo que impide que un XSS se lleve la sesión de un panel que
  // da shell. Se comprueba por partida doble: el atributo, y que el
  // JavaScript de la página efectivamente no la ve.
  expect(sesion.httpOnly, 'la cookie de sesión NO es HttpOnly').toBe(true)
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    'muxspace_session',
  )
})

test('el sidebar lista las sesiones de tmux que ya existían', async ({
  page,
  entorno,
  tmux,
}) => {
  // Creada por fuera del panel, directamente en tmux: es la mitad que importa.
  // Si el test creara la sesión por el propio panel, un backend que devolviera
  // lo que le acaban de mandar pasaría igual.
  const previa = nombreSesion('-previa')
  tmux(['new-session', '-d', '-s', previa])

  await entrar(page, entorno)

  await expect(sesionEnLista(page, previa)).toBeVisible()
})

test('crear una sesión desde el panel la crea de verdad en tmux', async ({
  page,
  entorno,
  tmux,
}) => {
  await entrar(page, entorno)
  const nombre = nombreSesion('-nueva')

  await page.getByRole('button', { name: T['sidebar.new_session'] }).click()
  await campoNombreSesion(page).fill(nombre)
  await page.getByRole('button', { name: T['form.create_session'] }).click()

  await expect(sesionEnLista(page, nombre)).toBeVisible()

  // La comprobación que de verdad cierra el caso: existe en tmux. Un `<li>`
  // en el DOM lo pinta cualquier optimistic update.
  const existe = tmux(['has-session', '-t', `=${nombre}`], { permitirFallo: true })
  expect(existe, `tmux no tiene la sesión ${nombre}`).not.toBeNull()
})

test('crear una sesión con un nombre ya usado muestra el error traducido', async ({
  page,
  entorno,
  tmux,
}) => {
  const nombre = nombreSesion('-duplicada')
  tmux(['new-session', '-d', '-s', nombre])

  await entrar(page, entorno)
  await page.getByRole('button', { name: T['sidebar.new_session'] }).click()
  await campoNombreSesion(page).fill(nombre)
  await page.getByRole('button', { name: T['form.create_session'] }).click()

  // El mensaje lleva el nombre interpolado: se comprueba el trozo estable de
  // la plantilla más el nombre, no la cadena entera con sus comillas.
  const esperado = T['err.session_exists'].replace('{name}', nombre)
  await expect(page.getByText(esperado)).toBeVisible()
})

test('el recorrido entero no deja errores en la consola del navegador', async ({
  page,
  entorno,
  tmux,
  consola,
}) => {
  // La fixture `consola` ya falla el test si hubo una violación de CSP; este
  // sube el listón a "ningún error de consola en absoluto" y recorre el
  // camino completo de una vez, que es cuando la CSP tiene más ocasiones de
  // quejarse (login, fetch, render del sidebar, modal, creación).
  const previa = nombreSesion('-consola')
  tmux(['new-session', '-d', '-s', previa])

  await entrar(page, entorno)
  await expect(sesionEnLista(page, previa)).toBeVisible()

  const nombre = nombreSesion('-consola2')
  await page.getByRole('button', { name: T['sidebar.new_session'] }).click()
  await campoNombreSesion(page).fill(nombre)
  await page.getByRole('button', { name: T['form.create_session'] }).click()
  await expect(sesionEnLista(page, nombre)).toBeVisible()

  const errores = consola.erroresInesperados()
  expect(errores, `errores en consola: ${JSON.stringify(errores, null, 2)}`).toEqual(
    [],
  )
  expect(consola.errores, 'excepciones sin capturar en la página').toEqual([])
})

test('todo lo que crea el E2E lleva su prefijo', async ({ tmux }) => {
  // El teardown mata SOLO lo que empieza por el prefijo. Si algún test creara
  // una sesión sin él, quedaría viva y este test es quien lo dice — mejor
  // aquí que descubriéndolo por sesiones huérfanas semanas después.
  const listado = tmux(['list-sessions', '-F', '#S'], { permitirFallo: true }) || ''
  const sueltas = listado
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
    .filter((s) => !s.startsWith(PREFIJO_SESION))

  expect(sueltas, 'sesiones sin el prefijo del E2E').toEqual([])
})
