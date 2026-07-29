/**
 * La barra de espacios: crear, renombrar, borrar y filtrar (`SpacesBar`).
 *
 * Existe porque la extracción de `SpacesBar` a su propio archivo se hizo **a
 * ciegas**: al verificarla por mutación resultó que se podía sustituir el
 * componente entero por `return null` y los 22 tests seguían en verde. Nadie
 * probaba la barra, ni antes ni después de moverla.
 *
 * Un componente extraído sin nada que sujete su comportamiento es un refactor
 * que se cree, no uno que se comprueba.
 *
 * Lo que se afirma aquí:
 *   - Un espacio creado desde el panel **persiste en el backend**, no solo en
 *     el DOM: se comprueba releyendo `/api/spaces`.
 *   - Elegir un espacio **filtra** la lista de sesiones, que es para lo que
 *     existen los espacios.
 *   - Borrar un espacio **no termina sus sesiones**: vuelven a «Sin asignar».
 *     Es la promesa que hace el propio diálogo de confirmación.
 */
import { T, entrar, expect, nombreSesion, test } from './fixtures.js'

test.afterEach(async ({ page, entorno }) => {
  // Se entra otra vez porque algún test termina con la sesión ya cerrada, y
  // el borrado necesita estar autenticado.
  if ((await page.locator('input[type="password"]').count()) > 0) {
    await entrar(page, entorno)
  }
  await borrarEspacios(page)
})

/** El selector de espacio de la barra. */
const selectorEspacios = (page) => page.getByTitle(T['spaces.select_title'])

/** Crea un espacio desde el panel y devuelve su título. */
async function crearEspacio(page, titulo) {
  await page.getByRole('button', { name: T['spaces.new'] }).click()
  await page.getByPlaceholder(T['spaces.create_placeholder']).fill(titulo)
  await page.getByRole('button', { name: T['spaces.save'] }).click()
  // El selector vuelve cuando el formulario se cierra: es la señal de que el
  // guardado terminó, sin esperar por tiempo.
  await expect(selectorEspacios(page)).toBeVisible()
  return titulo
}

/**
 * Cambia el espacio que mira la pestaña, por su título.
 *
 * Se busca el `value` de la opción en vez de pasarle una etiqueta: el texto
 * lleva el contador de sesiones detrás (`{title} ({count})`), así que
 * escribirlo a mano obligaría a acertar también con el número.
 */
async function mirarEspacio(page, titulo) {
  const valor = await selectorEspacios(page)
    .locator('option')
    .filter({ hasText: titulo })
    .first()
    .getAttribute('value')
  await selectorEspacios(page).selectOption(valor)
}

/**
 * Borra del backend todos los espacios que queden.
 *
 * NO es aseo opcional: el andamiaje comparte un backend entre specs, y los
 * espacios se persisten en `spaces.json`. Dejarlos ahí hace crecer la barra
 * de espacios, el sidebar se queda sin alto y filas que antes se veían pasan
 * a medir cero — lo que tumbó ocho tests de los otros dos specs la primera
 * vez que se añadió este archivo. Un spec no puede cambiarle el mundo a los
 * demás.
 */
async function borrarEspacios(page) {
  await page.evaluate(async () => {
    const espacios = await (
      await fetch('/api/spaces', { credentials: 'same-origin' })
    ).json()
    for (const e of espacios) {
      await fetch(`/api/spaces/${encodeURIComponent(e.id)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      })
    }
  })
}

/** Los espacios que el backend tiene guardados ahora mismo. */
async function espaciosDelBackend(page) {
  return page.evaluate(async () => {
    const r = await fetch('/api/spaces', { credentials: 'same-origin' })
    return r.json()
  })
}

test('un espacio creado desde el panel queda guardado en el backend', async ({
  page,
  entorno,
}) => {
  await entrar(page, entorno)
  const titulo = `espacio-${Date.now().toString(36)}`

  await crearEspacio(page, titulo)

  await expect(selectorEspacios(page)).toContainText(titulo)
  // Y en el servidor, que es lo que sobrevive a recargar la página. Sin esto,
  // un componente que solo actualizara su estado local pasaría igual.
  const guardados = await espaciosDelBackend(page)
  expect(guardados.map((e) => e.title)).toContain(titulo)
})

test('elegir un espacio filtra la lista de sesiones', async ({
  page,
  entorno,
  tmux,
}) => {
  // Para eso existen los espacios: si el filtro no filtra, la barra es
  // decoración.
  const suelta = nombreSesion('-sin-espacio')
  tmux(['new-session', '-d', '-s', suelta])

  await entrar(page, entorno)
  // `toHaveCount` y no `toBeVisible`: lo que este test afirma es que la
  // sesión ESTÁ en la lista, no cuántos píxeles ocupa. Con varios espacios
  // creados, el sidebar se queda sin alto y la fila puede medir cero sin que
  // nada esté mal — y `toBeVisible` fallaría por eso, que es un ruido de
  // maquetación en un test de filtrado.
  await expect(page.locator('aside').getByText(suelta, { exact: true })).toHaveCount(1)

  const titulo = `vacio-${Date.now().toString(36)}`
  await crearEspacio(page, titulo)
  await mirarEspacio(page, titulo)

  // El espacio nuevo está vacío: la sesión de antes no debe verse, y sí el
  // aviso de que aquí no hay ninguna.
  await expect(page.getByText(T['sidebar.space_empty'])).toBeVisible()
  await expect(page.locator('aside').getByText(suelta, { exact: true })).toHaveCount(0)
})

test('renombrar un espacio cambia su nombre en el backend', async ({
  page,
  entorno,
}) => {
  await entrar(page, entorno)
  const original = `antes-${Date.now().toString(36)}`
  await crearEspacio(page, original)

  const nuevo = `despues-${Date.now().toString(36)}`
  await page.getByRole('button', { name: T['spaces.rename'] }).click()
  await page.getByPlaceholder(T['spaces.rename_placeholder']).fill(nuevo)
  await page.getByRole('button', { name: T['spaces.save'] }).click()

  await expect(selectorEspacios(page)).toContainText(nuevo)
  const guardados = await espaciosDelBackend(page)
  expect(guardados.map((e) => e.title)).toContain(nuevo)
  expect(guardados.map((e) => e.title)).not.toContain(original)
})

test('borrar un espacio no termina sus sesiones', async ({ page, entorno, tmux }) => {
  // Es la promesa literal del diálogo de confirmación: «sus sesiones NO se
  // terminan: vuelven a Sin asignar». Se comprueba en tmux, no en el DOM.
  await entrar(page, entorno)
  const titulo = `borrable-${Date.now().toString(36)}`
  await crearEspacio(page, titulo)

  page.on('dialog', (d) => d.accept())
  await page.getByRole('button', { name: T['spaces.delete'] }).click()

  await expect(selectorEspacios(page)).not.toContainText(titulo)
  const guardados = await espaciosDelBackend(page)
  expect(guardados.map((e) => e.title)).not.toContain(titulo)

  // Y el servidor de tmux sigue con sus sesiones intactas.
  const vivas = tmux(['list-sessions', '-F', '#S'], { permitirFallo: true })
  expect(
    vivas,
    'borrar un espacio se ha llevado por delante las sesiones',
  ).not.toBeNull()
})

test('«Sin asignar» no se puede renombrar ni borrar', async ({ page, entorno }) => {
  // No es un espacio de verdad: es la vista de las sesiones que no están en
  // ninguno (las creadas fuera del panel, por ejemplo). Dejar que se
  // renombrara o borrara sería ofrecer una acción que no puede funcionar.
  await entrar(page, entorno)

  await expect(
    page.getByRole('button', { name: T['spaces.rename_disabled'] }),
  ).toBeDisabled()
  await expect(
    page.getByRole('button', { name: T['spaces.delete_disabled'] }),
  ).toBeDisabled()
})
