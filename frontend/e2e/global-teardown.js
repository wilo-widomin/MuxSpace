/**
 * Para el backend de pruebas, mata sus sesiones de tmux y borra su temporal.
 *
 * El orden importa: primero las sesiones (mientras el wrapper y el socket aún
 * existen), después el backend, y el temporal al final. Al revés, borrar el
 * temporal se llevaría por delante el wrapper que hace falta para hablar con
 * el servidor de tmux que hay que apagar.
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'

import { DIR_TMP, PREFIJO_SESION, RUTA_ENTORNO, leerEntorno } from './entorno.js'

function matarSesionesDelE2E(wrapperTmux) {
  let listado
  try {
    listado = execFileSync(wrapperTmux, ['list-sessions', '-F', '#S'], {
      encoding: 'utf8',
    })
  } catch {
    return [] // "no server running": no queda nada que matar.
  }
  // SOLO las que llevan nuestro prefijo, aunque el servidor sea propio y un
  // `kill-server` fuera igual de seguro. Si algún día alguien decide compartir
  // socket "solo para depurar", esta línea es la que evita el desastre.
  const nuestras = listado
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s.startsWith(PREFIJO_SESION))
  for (const sesion of nuestras) {
    try {
      execFileSync(wrapperTmux, ['kill-session', '-t', sesion])
    } catch {
      // Ya no estaba: nada que hacer.
    }
  }
  return nuestras
}

export default async function globalTeardown() {
  if (!fs.existsSync(RUTA_ENTORNO)) return // el setup no llegó a terminar
  const entorno = leerEntorno()

  const muertas = matarSesionesDelE2E(entorno.wrapperTmux)
  if (muertas.length) console.log(`[e2e] sesiones retiradas: ${muertas.join(', ')}`)

  try {
    execFileSync(entorno.wrapperTmux, ['kill-server'])
  } catch {
    // No había servidor, o ya se apagó al morir su última sesión.
  }

  try {
    process.kill(entorno.pid, 'SIGTERM')
  } catch {
    // Ya había muerto.
  }
  // Que termine de cerrar antes de tirarle el directorio de debajo.
  for (let i = 0; i < 50; i++) {
    try {
      process.kill(entorno.pid, 0)
    } catch {
      break
    }
    await new Promise((r) => setTimeout(r, 100))
  }
  try {
    process.kill(entorno.pid, 'SIGKILL')
  } catch {
    // Lo normal: ya no está.
  }

  fs.rmSync(entorno.raizTmp, { recursive: true, force: true })
  // El log se conserva: si un test falló, es lo primero que hay que mirar.
  fs.rmSync(RUTA_ENTORNO, { force: true })
  console.log(`[e2e] temporal borrado (${entorno.raizTmp}); log en ${DIR_TMP}`)
}
