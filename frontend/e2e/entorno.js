/**
 * Parámetros del backend de pruebas, compartidos entre el arranque y los tests.
 *
 * El `globalSetup` corre en el proceso principal de Playwright y los tests en
 * procesos worker aparte: no comparten memoria. En vez de confiar en que
 * `process.env` se herede (que depende de cuándo se bifurque cada worker), el
 * arranque escribe un JSON y los tests lo leen. Es explícito y se puede mirar
 * a mano cuando algo falla.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const AQUI = path.dirname(fileURLToPath(import.meta.url))

/** Directorio de trabajo del E2E. Fuera de git (ver .gitignore). */
export const DIR_TMP = path.join(AQUI, '.tmp')

/** Dónde el arranque deja los parámetros para los tests. */
export const RUTA_ENTORNO = path.join(DIR_TMP, 'entorno.json')

/**
 * Prefijo de TODAS las sesiones de tmux que crea el E2E.
 *
 * El teardown mata solo las que empiezan por aquí. Es la segunda red: la
 * primera es que el E2E habla con un servidor de tmux propio, seleccionado
 * por socket (`-L`), donde el usuario no tiene nada.
 */
export const PREFIJO_SESION = 'muxspace-e2e-'

export function guardarEntorno(entorno) {
  fs.mkdirSync(DIR_TMP, { recursive: true })
  fs.writeFileSync(RUTA_ENTORNO, JSON.stringify(entorno, null, 2))
}

export function leerEntorno() {
  if (!fs.existsSync(RUTA_ENTORNO)) {
    throw new Error(
      `No hay ${RUTA_ENTORNO}: el globalSetup no llegó a arrancar el backend ` +
        'de pruebas. Mira la salida de Playwright más arriba.',
    )
  }
  return JSON.parse(fs.readFileSync(RUTA_ENTORNO, 'utf8'))
}
