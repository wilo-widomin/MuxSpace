/**
 * La biblioteca: crear un comando y lanzarlo, crear un proyecto y ejecutarlo.
 *
 * El backend de esto está bien probado —`library_store.py` al 100% y los
 * endpoints `launch` y `run-project` cubiertos por los tests de auditoría—,
 * pero **el recorrido por el panel no lo probaba nadie**: `accesibilidad.spec`
 * abre estos dos modales y ni siquiera envía el formulario.
 *
 * Y no es un hueco cualquiera. Lanzar un comando o ejecutar un proyecto pasa
 * por `_tmux_safe_label` y `_next_label_name`, que es **exactamente donde
 * vivía S17**: una etiqueta que empezaba por `$` creaba una sesión que el
 * panel no podía matar nunca, porque tmux leía `$X` como un ID de sesión y no
 * como un nombre. Aquello se arregló con tests de `tmux_service`; lo que
 * faltaba era comprobar la cadena entera desde el navegador.
 *
 * Por eso los nombres de aquí llevan `$` y espacios a propósito: son los que
 * rompieron esto una vez.
 */
import { PREFIJO_SESION, leerEntorno } from './entorno.js'
import { T, entrar, expect, sesionEnLista, test } from './fixtures.js'

/** Abre la sección plegable del sidebar cuyo título se pasa. */
async function abrirSeccion(page, titulo) {
  await page.getByRole('button', { name: titulo, exact: true }).click()
}

/**
 * Deja el servidor de tmux del E2E sin sesiones.
 *
 * Igual que en `terminal.spec`: el andamiaje comparte servidor entre specs y
 * el panel abre un tile por sesión. Sin esto, los localizadores de aquí
 * competirían con media docena de terminales de otros tests.
 */
function limpiarSesiones(tmux) {
  const listado = tmux(['list-sessions', '-F', '#S'], { permitirFallo: true }) || ''
  for (const s of listado
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)) {
    tmux(['kill-session', '-t', `=${s}`], { permitirFallo: true })
  }
}

/** Las sesiones que hay ahora mismo en el servidor de tmux del E2E. */
function sesiones(tmux) {
  const listado = tmux(['list-sessions', '-F', '#S'], { permitirFallo: true }) || ''
  return listado
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Crea un comando en la biblioteca y devuelve su etiqueta. */
async function crearComando(page, etiqueta, comando = 'echo hola') {
  await page.getByRole('button', { name: T['sidebar.new_command'] }).click()
  await page.getByLabel(T['form.name_optional_label']).fill(etiqueta)
  await page.getByLabel(T['form.command_label']).fill(comando)
  await page.getByRole('button', { name: T['form.save'], exact: true }).click()
  await expect(page.locator('aside').getByText(etiqueta, { exact: true })).toBeVisible()
  return etiqueta
}

/**
 * El botón de lanzar un comando de la biblioteca.
 *
 * Su nombre accesible **cambia según el foco**: sin terminal activa dice
 * «Abrir en sesión nueva y ejecutar»; con una activa, «Ejecutar en la
 * terminal X», porque hace otra cosa. No es un detalle de maquetación, es la
 * diferencia entre crear una sesión y escribir en una que ya existe — y por
 * eso el localizador tiene que ser explícito sobre cuál de los dos espera.
 */
const botonLanzarEnSesionNueva = (page) =>
  page.getByRole('button', { name: T['sidebar.run_in_new_session'] }).first()

test.beforeEach(async ({ tmux }) => {
  limpiarSesiones(tmux)
})

test.afterEach(async ({ page, entorno }) => {
  // La biblioteca se persiste en `library.json` y el backend es compartido:
  // dejar comandos y proyectos ahí haría crecer el sidebar para los demás
  // specs, que es el mismo problema que ya dio el spec de espacios.
  if ((await page.locator('input[type="password"]').count()) > 0) {
    await entrar(page, entorno)
  }
  await page.evaluate(async () => {
    for (const recurso of ['commands', 'projects']) {
      const items = await (
        await fetch(`/api/${recurso}`, { credentials: 'same-origin' })
      ).json()
      for (const it of items) {
        await fetch(`/api/${recurso}/${encodeURIComponent(it.id)}`, {
          method: 'DELETE',
          credentials: 'same-origin',
        })
      }
    }
  })
})

test('un comando creado en el panel se lanza y crea su sesión en tmux', async ({
  page,
  entorno,
  tmux,
}) => {
  await entrar(page, entorno)
  await abrirSeccion(page, T['sidebar.commands'])

  // La etiqueta empieza por `$` y lleva espacios: es el caso de S17. El
  // backend tiene que convertirla en un nombre de sesión manejable, y sobre
  // todo en uno que después se pueda MATAR.
  await crearComando(
    page,
    `${PREFIJO_SESION}$eco con espacios`,
    'echo hola-desde-la-biblioteca',
  )

  // Al lanzarlo, existe en tmux de verdad.
  await botonLanzarEnSesionNueva(page).click()

  await expect
    .poll(() => sesiones(tmux), { message: 'el lanzamiento no creó ninguna sesión' })
    .not.toEqual([])

  const creada = sesiones(tmux)[0]
  // El `$` NO puede llegar al nombre de la sesión: con él, tmux lo lee como
  // el prefijo de un ID y la sesión se vuelve inmatable (S17).
  expect(creada, `el nombre de la sesión conserva el $: ${creada}`).not.toContain('$')
  await expect(sesionEnLista(page, creada)).toBeVisible()
})

test('la sesión que crea un comando con «$» se puede matar', async ({
  page,
  entorno,
  tmux,
}) => {
  // El corazón de S17. Crear la sesión nunca falló; lo que fallaba era
  // cerrarla, y el usuario se quedaba con una terminal fantasma para siempre.
  await entrar(page, entorno)
  await abrirSeccion(page, T['sidebar.commands'])

  await crearComando(page, `${PREFIJO_SESION}$raro`, 'echo x')
  await botonLanzarEnSesionNueva(page).click()

  await expect.poll(() => sesiones(tmux)).not.toEqual([])
  const creada = sesiones(tmux)[0]

  page.on('dialog', (d) => d.accept())
  await page
    .locator('aside')
    .getByRole('button', { name: T['sidebar.kill_session'] })
    .first()
    .click()

  await expect
    .poll(() => sesiones(tmux), {
      message: `la sesión ${creada} no se pudo matar desde el panel (S17)`,
    })
    .toEqual([])
})

test('un proyecto creado en el panel se ejecuta y crea su sesión', async ({
  page,
  entorno,
  tmux,
}) => {
  await entrar(page, entorno)

  // Los comandos de un proyecto se ELIGEN de la biblioteca, no se escriben:
  // `CommandSelect` es un `<select>`. Así que primero hay que tener uno.
  await abrirSeccion(page, T['sidebar.commands'])
  await crearComando(page, `${PREFIJO_SESION}paso`, 'pwd')

  await abrirSeccion(page, T['sidebar.projects'])
  const titulo = `${PREFIJO_SESION}proyecto de prueba`
  await page.getByRole('button', { name: T['sidebar.new_project'] }).click()
  await page.getByLabel(T['form.title_label']).fill(titulo)
  await page.getByLabel(T['form.directory_label']).fill(leerEntorno().raizSubidas)
  await page.locator('form select').last().selectOption('pwd')
  await page.getByRole('button', { name: T['form.save_project'] }).click()

  // `.first()`: el título del proyecto sale dos veces en el sidebar (la fila
  // de la lista y el botón que lo abre en una pestaña nueva). Lo que se
  // afirma aquí es que el proyecto se guardó, no cuántas veces se pinta.
  await expect(
    page.locator('aside').getByText(titulo, { exact: true }).first(),
  ).toBeVisible()

  await page.getByRole('button', { name: T['sidebar.run_project'] }).first().click()

  await expect
    .poll(() => sesiones(tmux), { message: 'ejecutar el proyecto no creó sesión' })
    .not.toEqual([])

  // La sesión se llama COMO EL PROYECTO —es el diseño: el título del proyecto
  // es el nombre de la sesión de tmux—, así que su nombre sale dos veces en
  // el sidebar: en la lista de sesiones y en la de proyectos. De ahí el
  // `.first()`, y no un localizador más fino: lo que se comprueba es que la
  // sesión que tmux dice tener aparece en el panel.
  const creada = sesiones(tmux)[0]
  expect(creada).toContain('proyecto de prueba')
  await expect(sesionEnLista(page, creada).first()).toBeVisible()
})

test('lanzar dos veces el mismo comando no colisiona de nombre', async ({
  page,
  entorno,
  tmux,
}) => {
  // `_next_label_name` añade « (N)» cuando el nombre ya está cogido. Sin eso,
  // el segundo lanzamiento chocaría con el primero: es la otra mitad de la
  // lógica que comparte camino con S17.
  await entrar(page, entorno)
  await abrirSeccion(page, T['sidebar.commands'])

  await crearComando(page, `${PREFIJO_SESION}doble`, 'echo x')

  await botonLanzarEnSesionNueva(page).click()
  await expect.poll(() => sesiones(tmux).length).toBe(1)

  // Hay que cerrar el tile antes de volver a lanzar. No es un rodeo del test:
  // con una terminal enfocada, ese botón deja de crear sesiones y pasa a
  // escribir en la que tiene el foco. Cerrar la vista libera el foco (la
  // sesión sigue viva, así que su nombre sigue cogido, que es justo lo que
  // hace falta para probar `_next_label_name`).
  await page.getByRole('button', { name: T['tile.close'] }).first().click()

  await botonLanzarEnSesionNueva(page).click()
  await expect
    .poll(() => sesiones(tmux).length, {
      message: 'el segundo lanzamiento no creó una sesión propia',
    })
    .toBe(2)

  // Y son dos nombres distintos, no uno pisado.
  expect(new Set(sesiones(tmux)).size).toBe(2)
})
