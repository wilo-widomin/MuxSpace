/**
 * E2E: abrir una terminal y ver el eco (US-025).
 *
 * Es el único test que recorre la cadena entera —WebSocket → `pty_bridge` →
 * PTY → tmux → xterm.js— y por tanto el único que puede decir que el panel
 * hace lo que dice hacer. También es la red que US-021 necesitaba para tocar
 * el puente con algo de tranquilidad.
 *
 * Todo lo que se espera se espera **por condición**, nunca por tiempo. En un
 * test con tantas piezas móviles, un `sleep` fijo es la receta exacta de un
 * rojo intermitente: si en esta máquina tmux tarda 200 ms y en otra 900, el
 * test miente en una de las dos.
 *
 * Reutiliza el andamiaje de US-024 (arranque del backend, aislamiento de
 * tmux, prefijo y teardown). No hay un segundo montaje.
 */
import { T, entrar, expect, nombreSesion, sesionEnLista, test } from './fixtures.js'

/** Retira todas las sesiones del servidor de tmux del E2E. */
function limpiarSesiones(tmux) {
  const listado = tmux(['list-sessions', '-F', '#S'], { permitirFallo: true }) || ''
  for (const sesion of listado.split('\n').map((x) => x.trim()).filter(Boolean)) {
    tmux(['kill-session', '-t', `=${sesion}`], { permitirFallo: true })
  }
}

/**
 * El tile de una sesión concreta, dentro del grid.
 *
 * Hace falta acotar: el panel abre un tile por cada sesión de tmux, y como
 * el andamiaje comparte servidor entre tests, para cuando corre este spec ya
 * hay media docena. Un `.xterm-rows` a secas casa con todas y Playwright
 * falla por ambigüedad — con razón.
 *
 * Se localiza por el nombre en la cabecera del tile y se sube al contenedor
 * con `..`: la alternativa sería meter un `data-testid` en `TerminalTile`, y
 * la US deja fuera tocar el componente.
 */
const tileDe = (page, nombre) =>
  page
    .getByRole('main')
    .locator('div')
    // Los DOS filtros: el nombre lo llevan también los `div` de la cabecera
    // (que no contienen la terminal), y la terminal la contienen también los
    // contenedores del grid (que llevan además los nombres de los otros
    // tiles). Solo el `div` raíz del tile cumple las dos cosas... y sus
    // ancestros, de ahí el `.last()`: el más interno de los que cumplen.
    .filter({ has: page.getByText(nombre, { exact: true }) })
    .filter({ has: page.locator('.xterm-rows') })
    .last()

/** Lo que xterm.js tiene pintado en el tile de esa sesión. */
const pantalla = (page, nombre) => tileDe(page, nombre).locator('.xterm-rows')

/**
 * Crea una sesión de tmux, entra al panel y abre su terminal en el grid.
 *
 * La sesión se crea **por fuera del panel**, con tmux directamente: así el
 * test prueba que el panel se conecta a una sesión que ya existía, que es lo
 * que pasa de verdad al abrir el navegador por la mañana.
 */
async function abrirTerminal(page, entorno, tmux, sufijo) {
  // Grid limpio. El andamiaje comparte servidor de tmux entre tests y el
  // panel abre un tile por cada sesión: sin esto, para cuando corre este spec
  // hay media docena de terminales repartiéndose la pantalla, cada una
  // demasiado pequeña para que quepa lo que se escribe, y varios botones
  // "Cerrar" idénticos. Se retiran solo sesiones con el prefijo del E2E, que
  // son las únicas que puede haber en este servidor.
  limpiarSesiones(tmux)

  const nombre = nombreSesion(sufijo)
  tmux(['new-session', '-d', '-s', nombre])
  await entrar(page, entorno)

  await sesionEnLista(page, nombre).click()

  // El prompt: la señal de que el PTY está vivo y xterm.js está pintando lo
  // que sale de él. Se espera a que la pantalla tenga ALGO, no a un `$`
  // concreto: el prompt del usuario que corra la suite es el que sea.
  await expect(pantalla(page, nombre)).not.toBeEmpty()
  return nombre
}

/**
 * El WebSocket del terminal de `nombre`, entre todos los que abrió la página.
 *
 * Por nombre y no "el primero que apunte a /api/terminal/": el panel abre uno
 * por tile, y coger el primero haría que el test afirmara cosas sobre la
 * terminal de otra sesión.
 */
function wsDeLaSesion(websockets, nombre) {
  return websockets.find((ws) => decodeURIComponent(ws.url()).endsWith(`/api/terminal/${nombre}`))
}

/** Escribe en la terminal de `nombre` y pulsa Enter. */
async function teclear(page, nombre, texto) {
  await tileDe(page, nombre).locator('.xterm-screen').click()
  await page.keyboard.type(texto)
  await page.keyboard.press('Enter')
}

test('la terminal se conecta, pinta el prompt y devuelve el eco', async ({
  page,
  entorno,
  tmux,
}) => {
  const nombre = await abrirTerminal(page, entorno, tmux, '-eco')

  // Marca única: si se buscara "hola" a secas, el test pasaría con el texto
  // que el propio usuario dejó escrito en el prompt de la sesión.
  const marca = `eco-${Math.random().toString(36).slice(2, 8)}`
  await teclear(page, nombre, `echo ${marca}`)

  // `toContainText` reintenta hasta el timeout de `expect`: espera activa por
  // el contenido renderizado, sin un solo `waitForTimeout`.
  await expect(pantalla(page, nombre)).toContainText(marca)
})

test('el WebSocket del terminal se abre sin que la CSP se queje', async ({
  page,
  entorno,
  tmux,
  consola,
}) => {
  // El riesgo que el plan dejó abierto en la fase 0.1: la CSP declara
  // `default-src 'self'` y no una `connect-src` explícita, así que si algún
  // navegador no casara `ws://` del mismo origen bajo `default-src`, la
  // terminal dejaría de conectar. Aquí se cierra formalmente.
  const websockets = []
  page.on('websocket', (ws) => websockets.push(ws))

  const nombre = await abrirTerminal(page, entorno, tmux, '-csp')

  expect(websockets.length, 'no se abrió ningún WebSocket').toBeGreaterThan(0)
  const terminal = wsDeLaSesion(websockets, nombre)
  expect(terminal, 'no se abrió el WebSocket del terminal').toBeTruthy()
  expect(terminal.isClosed(), 'el WebSocket se cerró nada más abrirse').toBe(false)

  // La fixture `consola` ya falla si hubo violación de CSP; se afirma aquí
  // además, para que este test diga por sí solo qué estaba comprobando.
  expect(consola.violacionesCSP()).toEqual([])
})

test('redimensionar la ventana reajusta la terminal sin romper la conexión', async ({
  page,
  entorno,
  tmux,
}) => {
  const nombre = await abrirTerminal(page, entorno, tmux, '-resize')

  const antes = `antes-${Math.random().toString(36).slice(2, 8)}`
  await teclear(page, nombre, `echo ${antes}`)
  await expect(pantalla(page, nombre)).toContainText(antes)

  await page.setViewportSize({ width: 1400, height: 900 })

  // Que la conexión aguante se prueba usándola, no mirando un atributo: si el
  // resize hubiera tirado el WebSocket, este segundo eco no llegaría nunca.
  const despues = `despues-${Math.random().toString(36).slice(2, 8)}`
  await teclear(page, nombre, `echo ${despues}`)
  await expect(pantalla(page, nombre)).toContainText(despues)
})

test('cerrar el tile cierra el WebSocket pero la sesión de tmux sigue viva', async ({
  page,
  entorno,
  tmux,
}) => {
  // La diferencia entre "cerrar la vista" y "matar la sesión" es el corazón
  // del panel: se cierra la ventana y el trabajo de dentro sigue corriendo.
  const websockets = []
  page.on('websocket', (ws) => websockets.push(ws))

  const nombre = await abrirTerminal(page, entorno, tmux, '-cerrar')
  const terminal = wsDeLaSesion(websockets, nombre)

  await tileDe(page, nombre).getByRole('button', { name: T['tile.close'] }).click()

  await expect
    .poll(() => terminal.isClosed(), {
      message: 'el WebSocket siguió abierto tras cerrar el tile',
    })
    .toBe(true)

  // Y lo que de verdad importa: la sesión NO se ha muerto.
  const viva = tmux(['has-session', '-t', `=${nombre}`], { permitirFallo: true })
  expect(viva, `cerrar el tile mató la sesión ${nombre}`).not.toBeNull()
})

test('matar la sesión desde el panel cierra la terminal', async ({
  page,
  entorno,
  tmux,
}) => {
  const websockets = []
  page.on('websocket', (ws) => websockets.push(ws))

  const nombre = await abrirTerminal(page, entorno, tmux, '-matar')
  const terminal = wsDeLaSesion(websockets, nombre)

  // El botón pide confirmación con `window.confirm`: sin este manejador,
  // Playwright descarta el diálogo por defecto y el kill no llega a ocurrir.
  page.on('dialog', (d) => d.accept())
  await tileDe(page, nombre).getByRole('button', { name: T['tile.kill'] }).click()

  await expect
    .poll(() => terminal.isClosed(), {
      message: 'la terminal siguió conectada tras matar la sesión',
    })
    .toBe(true)

  await expect
    .poll(
      () => tmux(['has-session', '-t', `=${nombre}`], { permitirFallo: true }),
      { message: `la sesión ${nombre} sigue en tmux tras el kill` },
    )
    .toBeNull()

  // Y desaparece del listado, que es lo que ve el usuario.
  await expect(sesionEnLista(page, nombre)).toHaveCount(0)
})
