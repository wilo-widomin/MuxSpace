/**
 * E2E: subir un archivo y comprobar la ruta copiada (US-026).
 *
 * Junta en un recorrido real el navegador de carpetas (US-003), la subida
 * (US-004) y `quotePath` (US-010/US-017). El corazón es **el
 * entrecomillado**: ese texto va directo a una terminal, y un escape mal
 * hecho no es una errata, es un comando que hace otra cosa.
 *
 * Dos comprobaciones que separan esto de una prueba de maquetación:
 *
 * 1. El archivo **existe en el disco** en la ruta esperada, mirado con `fs`.
 *    Que aparezca en el historial solo dice que el backend contestó.
 * 2. La ruta que queda **en el portapapeles**, leída con
 *    `navigator.clipboard.readText()`, no la que se pinta en la lista. Son
 *    dos caminos distintos en el componente y solo uno acaba en la terminal.
 *
 * Todo ocurre bajo la raíz temporal del backend de pruebas. Ni un byte fuera.
 */
import fs from 'node:fs'
import path from 'node:path'

import { T, entrar, expect, test } from './fixtures.js'

/**
 * `quotePath` del frontend, copiada aquí a propósito.
 *
 * Es contabilidad por partida doble: si el test importara la función del
 * código bajo prueba, comprobaría que la función es igual a sí misma y
 * pasaría con cualquier regla de escape, incluida una rota. Escrita a mano,
 * un cambio en `paths.js` que no sea intencionado pone esto en rojo.
 */
function entrecomillarEsperado(ruta) {
  if (!/[^\w@%+=:,./~-]/.test(ruta)) return ruta
  return `"${ruta.replace(/(["$`\\])/g, '\\$1')}"`
}

/** Abre la sección "Subir archivo" del sidebar. */
async function abrirSeccionSubida(page, entorno) {
  await entrar(page, entorno)
  await page.getByRole('button', { name: T['upload.title'] }).click()
  await expect(page.getByText(T['upload.dest_label'])).toBeVisible()
}

/** Elige la carpeta destino con el navegador de carpetas. */
async function elegirCarpeta(page) {
  await page.getByRole('button', { name: T['upload.choose_dir'] }).click()
  await expect(page.getByText(T['upload.browser_title'])).toBeVisible()
  await page.getByRole('button', { name: T['upload.save_here'] }).click()
  await expect(page.getByText(T['upload.browser_title'])).toHaveCount(0)
}

/**
 * Sube un archivo con el contenido dado y devuelve su ruta esperada.
 *
 * El `<input type="file">` está oculto (la zona visible es su `<label>`), así
 * que se le pasan los ficheros directamente: `setInputFiles` no necesita que
 * el elemento sea visible, y simular el diálogo nativo del sistema no aporta
 * nada a lo que este test comprueba.
 */
async function subir(page, entorno, nombre, contenido = 'contenido de prueba') {
  const origen = path.join(entorno.raizTmp, `origen-${Date.now()}`)
  fs.mkdirSync(origen, { recursive: true })
  const local = path.join(origen, nombre)
  fs.writeFileSync(local, contenido)

  await page.locator('input[type="file"]').setInputFiles(local)

  const destino = path.join(entorno.raizSubidas, nombre)
  await expect(page.getByText(T['upload.recent'])).toBeVisible()
  return destino
}

/** Lo que hay ahora mismo en el portapapeles del navegador. */
function leerPortapapeles(page) {
  return page.evaluate(() => navigator.clipboard.readText())
}

test.beforeEach(async ({ context, entorno }) => {
  // Sin estos permisos, `navigator.clipboard.writeText` lanza y el componente
  // cae a su camino alternativo (un `<textarea>` oculto + `execCommand`), que
  // es OTRO código. Aquí se prueba el camino normal, que es el que se ejecuta
  // en el navegador del usuario sobre HTTPS.
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], {
    origin: entorno.baseURL,
  })
})

test('subir un archivo lo deja en el disco y en el historial', async ({
  page,
  entorno,
}) => {
  await abrirSeccionSubida(page, entorno)
  await elegirCarpeta(page)

  const nombre = `notas-${Date.now()}.txt`
  const destino = await subir(page, entorno, nombre, 'hola desde el E2E')

  // En el DOM…
  await expect(page.getByText(nombre, { exact: true })).toBeVisible()
  // …y en el disco, que es lo que de verdad se afirma.
  expect(fs.existsSync(destino), `no existe ${destino}`).toBe(true)
  expect(fs.readFileSync(destino, 'utf8')).toBe('hola desde el E2E')

  // Y bajo la raíz del backend de pruebas: ni un byte fuera.
  expect(destino.startsWith(entorno.raizSubidas)).toBe(true)
})

test('la ruta de un nombre normal se copia tal cual, sin comillas', async ({
  page,
  entorno,
}) => {
  await abrirSeccionSubida(page, entorno)
  await elegirCarpeta(page)

  const nombre = `simple-${Date.now()}.txt`
  const destino = await subir(page, entorno, nombre)

  await page.getByRole('button', { name: nombre }).click()

  const copiado = await leerPortapapeles(page)
  expect(copiado).toBe(destino)
  expect(copiado, 'una ruta sin caracteres raros no debe llevar comillas').not.toContain(
    '"',
  )
})

test('un nombre con espacios se copia entrecomillado', async ({
  page,
  entorno,
}) => {
  // El caso que de verdad importa: sin comillas, `cat /tmp/mis notas.txt` son
  // dos argumentos y el comando hace otra cosa.
  await abrirSeccionSubida(page, entorno)
  await elegirCarpeta(page)

  const nombre = `mis notas ${Date.now()}.txt`
  const destino = await subir(page, entorno, nombre)

  await page.getByRole('button', { name: nombre }).click()

  const copiado = await leerPortapapeles(page)
  expect(copiado).toBe(entrecomillarEsperado(destino))
  expect(copiado.startsWith('"') && copiado.endsWith('"')).toBe(true)
  expect(copiado).toContain(nombre)
})

test('un nombre con $ y comillas se copia seguro de pegar en un shell', async ({
  page,
  entorno,
}) => {
  // `$HOME` sin escapar dentro de comillas dobles lo expande el shell, y una
  // comilla sin escapar CIERRA la cadena: lo que viniera detrás se
  // ejecutaría. Es el caso que convierte "copiar una ruta" en un problema de
  // seguridad.
  const nombre = `precio $HOME "raro" ${Date.now()}.txt`
  await abrirSeccionSubida(page, entorno)
  await elegirCarpeta(page)
  const destino = await subir(page, entorno, nombre)

  await page.getByRole('button', { name: nombre }).click()
  const copiado = await leerPortapapeles(page)

  expect(copiado).toBe(entrecomillarEsperado(destino))
  expect(copiado).toContain('\\$HOME')
  expect(copiado).toContain('\\"raro\\"')

  // La prueba de fondo: pegado en un shell de verdad, `echo` devuelve la ruta
  // EXACTA. Es lo único que demuestra que el entrecomillado sirve para lo que
  // existe; comparar cadenas solo prueba que dos expresiones regulares
  // coinciden.
  const { execFileSync } = await import('node:child_process')
  const devuelto = execFileSync('sh', ['-c', `printf '%s' ${copiado}`], {
    encoding: 'utf8',
  })
  expect(devuelto).toBe(destino)
})

test('quitar del historial no borra el archivo del disco', async ({
  page,
  entorno,
}) => {
  // "Quitar" retira el registro, jamás el archivo: el destino es una carpeta
  // real del usuario y el panel no borra ahí nada.
  await abrirSeccionSubida(page, entorno)
  await elegirCarpeta(page)

  const nombre = `conservado-${Date.now()}.txt`
  const destino = await subir(page, entorno, nombre)
  expect(fs.existsSync(destino)).toBe(true)

  // El botón de quitar está `hidden` y solo aparece con `group-hover`, así
  // que hay que pasar el ratón por la fila antes: sin el hover, el clic se
  // queda esperando a un elemento que nunca se hace visible.
  const fila = page
    .locator('li')
    .filter({ has: page.getByText(nombre, { exact: true }) })
  await fila.hover()
  await fila
    .getByRole('button', { name: T['upload.remove_aria'].replace('{name}', nombre) })
    .click()

  await expect(page.getByText(nombre, { exact: true })).toHaveCount(0)
  expect(
    fs.existsSync(destino),
    'quitar del historial ha borrado el archivo del disco',
  ).toBe(true)
})
