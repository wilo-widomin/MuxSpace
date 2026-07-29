/**
 * Fixtures compartidas por los E2E.
 *
 * Dos cosas que aporta y que no conviene repetir en cada spec:
 *
 * 1. **`consola`**: recoge todo lo que el navegador escupe por consola y las
 *    excepciones de página, y al terminar CADA test comprueba que no hubo
 *    ninguna violación de CSP. Va como fixture `auto` para que no dependa de
 *    que quien escriba el próximo test se acuerde de pedirla — la
 *    comprobación de la CSP es media justificación de la fase 6, y no puede
 *    quedar en un test suelto.
 * 2. **`tmux`**: hablar con el servidor de tmux del E2E, que es propio. Todo
 *    lo que se cree lleva el prefijo del teardown.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test as base, expect } from '@playwright/test'

import { PREFIJO_SESION, leerEntorno } from './entorno.js'

const AQUI = path.dirname(fileURLToPath(import.meta.url))

/** Los textos del panel, leídos del mismo JSON que usa la aplicación.
 *
 * Así una reescritura del copy no rompe el E2E: lo que se afirma es "sale el
 * mensaje de credenciales incorrectas", no una cadena concreta escrita a mano
 * en dos sitios que se desincronizan.
 */
export const T = JSON.parse(
  fs.readFileSync(path.join(AQUI, '..', 'src', 'i18n', 'locales', 'es.json'), 'utf8'),
)

/**
 * Localizadores del formulario de login, **por su etiqueta**.
 *
 * Hasta que se ataron los `<label>` a sus campos, esto no era posible: eran
 * etiquetas solo visuales, sin `for`/`id`, y `getByLabel` no encontraba nada.
 * Los tests usaban `input[autocomplete="username"]`, que funcionaba pero
 * describía el HTML en vez de lo que ve el usuario.
 *
 * Que ahora funcione NO es un detalle de estilo: `getByLabel` consulta el
 * árbol de accesibilidad, el mismo que usa un lector de pantalla. Si alguien
 * desatara una etiqueta, estos localizadores dejarían de encontrar su campo y
 * los tests se pondrían rojos — que es exactamente la regresión que se quiere
 * detectar.
 */
export const campoUsuario = (page) => page.getByLabel(T['login.username'])
export const campoPassword = (page) => page.getByLabel(T['login.password'])

/**
 * Una sesión, en la LISTA del sidebar.
 *
 * Acotado al `<aside>` a propósito: al abrir una sesión su nombre aparece
 * también en el tile del grid, y sin acotar el localizador casa con dos
 * elementos. Lo que se afirma aquí es "está en el listado".
 */
export const sesionEnLista = (page, nombre) =>
  page.locator('aside').getByText(nombre, { exact: true })

/**
 * Entra al panel con las credenciales del backend de pruebas.
 *
 * Vive aquí y no en cada spec porque lo necesitan todos: es el prólogo de
 * cualquier recorrido, no parte de lo que ninguno prueba.
 */
export async function entrar(page, entorno) {
  await campoUsuario(page).fill(entorno.usuario)
  await campoPassword(page).fill(entorno.password)
  await page.getByRole('button', { name: T['login.submit'] }).click()
  await expect(page.getByRole('button', { name: T['sidebar.logout'] })).toBeVisible()
}

/** Un nombre de sesión único y con el prefijo que el teardown reconoce. */
export function nombreSesion(sufijo = '') {
  return `${PREFIJO_SESION}${Date.now().toString(36)}${sufijo}`
}

/** Marcas de una violación de CSP en el mensaje de consola de Chromium. */
function esViolacionCSP(texto) {
  return (
    /Content Security Policy/i.test(texto) ||
    /Refused to (load|execute|connect|apply|frame)/i.test(texto)
  )
}

export const test = base.extend({
  // El `{}` vacío no es un descuido: Playwright INSPECCIONA el código de la
  // función para saber de qué otras fixtures depende, y exige la
  // desestructuración aunque no dependa de ninguna ("First argument must use
  // the object destructuring pattern"). Un `_fixtures` sin desestructurar
  // hace que la suite entera se niegue a arrancar.
  entorno: [
    async ({}, use) => {
      await use(leerEntorno())
    },
    { scope: 'test' },
  ],

  /** `tmux(['has-session', '-t', x])` contra el servidor del E2E. */
  tmux: [
    async ({ entorno }, use) => {
      const ejecutar = (args, { permitirFallo = false } = {}) => {
        try {
          return execFileSync(entorno.wrapperTmux, args, { encoding: 'utf8' })
        } catch (err) {
          if (permitirFallo) return null
          throw err
        }
      }
      await use(ejecutar)
    },
    { scope: 'test' },
  ],

  /**
   * Deja cada test en la página del panel, ya cargada.
   *
   * `auto` y en las fixtures en vez de un `beforeEach` por spec: ningún test
   * del E2E empieza en otro sitio, y olvidarlo produce un fallo confuso
   * ("no encuentro el campo de usuario") en lugar de uno claro.
   */
  irAlPanel: [
    async ({ page, entorno }, use) => {
      await page.goto(entorno.baseURL)
      await use(undefined)
    },
    { auto: true },
  ],

  /**
   * Vigilante de la consola del navegador. `auto`: se activa siempre.
   */
  consola: [
    async ({ page }, use) => {
      const mensajes = []
      const errores = []
      page.on('console', (msg) => {
        mensajes.push({
          tipo: msg.type(),
          texto: msg.text(),
          url: msg.location()?.url || '',
        })
      })
      page.on('pageerror', (err) => errores.push(String(err)))

      const registro = {
        mensajes,
        errores,
        violacionesCSP: () =>
          mensajes.filter((m) => esViolacionCSP(m.texto)).map((m) => m.texto),
        /**
         * Errores de consola que NO se esperan.
         *
         * Chromium apunta como `error` cualquier respuesta 4xx, incluido el
         * 401 de `/api/me` con el que el panel comprueba al cargar si ya hay
         * sesión. Ese 401 no es un fallo: es la respuesta correcta a "¿estoy
         * dentro?" cuando no lo estás, y el frontend la usa para decidir si
         * pinta el login. Se filtra por URL y código concretos —no por
         * "ignora los 401"— para que un 401 en cualquier otro sitio siga
         * poniendo el test en rojo.
         */
        erroresInesperados: () =>
          mensajes
            .filter((m) => m.tipo === 'error')
            .filter((m) => !(m.url.endsWith('/api/me') && m.texto.includes('401'))),
      }
      await use(registro)

      // Después del test, pase lo que pase dentro: la CSP de la fase 0 tiene
      // que aguantar el recorrido entero sin una sola queja. Es la
      // comprobación que aquella fase dejó pendiente de automatizar.
      expect(
        registro.violacionesCSP(),
        'el navegador se quejó de la Content-Security-Policy',
      ).toEqual([])
    },
    { auto: true },
  ],
})

export { expect }
