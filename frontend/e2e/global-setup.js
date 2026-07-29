/**
 * Levanta un MuxSpace de pruebas, aislado de todo lo del usuario.
 *
 * La regla que no se salta ni para depurar: **el E2E no toca `backend/data/`,
 * ni el `.env` real, ni el proceso de producción, ni el servidor de tmux del
 * usuario.** Aquí se implementa con tres aislamientos independientes, porque
 * uno solo se rompe sin que nadie se entere:
 *
 * 1. **Copia del backend en un temporal.** `main.py` calcula su `data/` como
 *    `Path(__file__).parent / "data"`, sin variable de entorno que lo cambie.
 *    Copiando los `.py` a un directorio temporal, ese cálculo cae dentro del
 *    temporal por construcción. Es el mismo truco que usa `_reencarnar_auth`
 *    en `test_auth.py`, y es mejor que una variable nueva: no hay forma de
 *    olvidarse de ponerla.
 * 2. **Servidor de tmux propio**, seleccionado por socket con `-L` a través de
 *    un wrapper que se le pasa en `MUXSPACE_TMUX_BINARY`. Dos sockets son dos
 *    procesos `tmux` que no comparten nada: ni sesiones, ni opciones, ni la
 *    posibilidad de que un `kill` en uno alcance al otro.
 * 3. **Puerto libre pedido al sistema**, nunca el 8000, que es donde corre el
 *    panel de verdad del usuario.
 *
 * El frontend se sirve desde el build (`dist/`) por el `StaticFiles` del
 * backend, no desde el dev server de Vite: así se prueba el mismo montaje que
 * producción, con las cabeceras de seguridad y la CSP puestas.
 */
import { spawn, execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { DIR_TMP, guardarEntorno } from './entorno.js'

const AQUI = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(AQUI, '..')
const RAIZ = path.resolve(FRONTEND, '..')
const BACKEND = path.join(RAIZ, 'backend')
const PYTHON = path.join(BACKEND, 'venv', 'bin', 'python')

/** Un puerto que el sistema nos diga que está libre ahora mismo. */
function puertoLibre() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
  })
}

async function esperarA(url, timeoutMs, proceso) {
  const limite = Date.now() + timeoutMs
  while (Date.now() < limite) {
    if (proceso.exitCode !== null) {
      throw new Error(
        `el backend de pruebas murió con código ${proceso.exitCode} antes de ` +
          `responder. Log: ${path.join(DIR_TMP, 'backend.log')}`,
      )
    }
    try {
      const r = await fetch(url)
      if (r.ok) return
    } catch {
      // Todavía no escucha; se reintenta.
    }
    await new Promise((r) => setTimeout(r, 100))
  }
  throw new Error(
    `el backend de pruebas no respondió en ${url} tras ${timeoutMs} ms. ` +
      `Log: ${path.join(DIR_TMP, 'backend.log')}`,
  )
}

/** ¿Sigue vivo ese proceso? */
function vivo(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

/**
 * Retira los temporales que dejaron ejecuciones anteriores interrumpidas.
 *
 * El teardown limpia lo suyo, pero solo si llega a ejecutarse. Un Ctrl-C, el
 * `timeout` de un script o un proceso muerto a mitad se lo saltan y dejan **un
 * servidor de tmux vivo indefinidamente** más su directorio. No es teórico:
 * cuatro se acumularon en esta máquina depurando un cuelgue del arranque.
 *
 * Solo se tocan directorios que empiezan por `muxspace-e2e-` dentro del
 * temporal del sistema, y el `kill-server` va por el wrapper que hay dentro de
 * cada uno — o sea, contra su propio socket. El servidor de tmux del usuario
 * vive en otro sitio y no hay forma de alcanzarlo desde aquí.
 *
 * Y si el backend de ese directorio **sigue vivo**, se deja en paz: significa
 * que hay otra ejecución en marcha (dos terminales a la vez) y llevársela por
 * delante sería peor que el residuo que se pretende limpiar.
 */
function limpiarRestos() {
  let retirados = 0
  for (const nombre of fs.readdirSync(os.tmpdir())) {
    if (!nombre.startsWith('muxspace-e2e-')) continue
    const dir = path.join(os.tmpdir(), nombre)
    try {
      const rutaPid = path.join(dir, 'backend.pid')
      if (fs.existsSync(rutaPid)) {
        const pid = Number(fs.readFileSync(rutaPid, 'utf8').trim())
        if (pid && vivo(pid)) continue // otra ejecución en marcha: ni tocarlo
      }
      const wrapper = path.join(dir, 'tmux')
      if (fs.existsSync(wrapper)) {
        try {
          execFileSync(wrapper, ['kill-server'], { stdio: 'ignore' })
        } catch {
          // No había servidor, o ya estaba muerto.
        }
      }
      fs.rmSync(dir, { recursive: true, force: true })
      retirados++
    } catch {
      // Un directorio de otro usuario, o borrado entre medias: se ignora.
    }
  }
  if (retirados) {
    process.stdout.write(
      `[e2e] retirados ${retirados} restos de ejecuciones interrumpidas\n`,
    )
  }
}

export default async function globalSetup() {
  // Se empieza limpio: un `.tmp` de una ejecución anterior que reventara a
  // medias tendría un `entorno.json` apuntando a un backend que ya no existe.
  fs.rmSync(DIR_TMP, { recursive: true, force: true })
  fs.mkdirSync(DIR_TMP, { recursive: true })

  // --- El frontend, compilado. No se sirve por el dev server. ---
  //
  // SIEMPRE, no solo si falta `dist/`. La versión anterior se saltaba la
  // compilación cuando ya existía un build, y eso deja la suite probando
  // código que no es el del árbol de trabajo: se cambia un componente, se
  // lanzan los E2E, salen verdes, y lo que se ha ejecutado es el build de la
  // vez anterior. Se detectó al verificar por mutación las etiquetas
  // accesibles — dos mutaciones que rompían la UI sobrevivieron porque no
  // llegaron a compilarse.
  //
  // Cuesta ~3 s de los ~24 que tarda la suite. Un verde que no se corresponde
  // con el código cuesta mucho más.
  //
  // La salida se CAPTURA en vez de heredarse (`stdio: 'inherit'`): heredando,
  // la compilación se quedaba colgada indefinidamente cuando la salida de
  // Playwright va a una tubería en vez de a una terminal, que es como se
  // ejecuta desde cualquier script. Con `pipe` no depende de eso, y si el
  // build falla su salida sale en el mensaje de error en vez de perderse.
  process.stdout.write('[e2e] compilando el frontend…\n')
  try {
    execFileSync('bun', ['run', 'build'], {
      cwd: FRONTEND,
      stdio: 'pipe',
      timeout: 180_000,
    })
  } catch (err) {
    throw new Error(
      `no se pudo compilar el frontend:\n${err.stdout || ''}\n${err.stderr || ''}`,
      { cause: err },
    )
  }

  // Antes de crear el nuestro: retirar lo que dejaron ejecuciones muertas.
  limpiarRestos()

  // --- Copia del backend en un temporal, con su data/ dentro ---
  const raizTmp = fs.mkdtempSync(path.join(os.tmpdir(), 'muxspace-e2e-'))
  const backendTmp = path.join(raizTmp, 'backend')
  fs.mkdirSync(backendTmp, { recursive: true })
  for (const archivo of fs.readdirSync(BACKEND)) {
    if (archivo.endsWith('.py')) {
      fs.copyFileSync(path.join(BACKEND, archivo), path.join(backendTmp, archivo))
    }
  }
  // `main.py` sirve el frontend desde `<padre del backend>/frontend/dist`. Un
  // enlace al de verdad para probar EL build real, no una copia que pudiera
  // quedarse vieja.
  fs.symlinkSync(FRONTEND, path.join(raizTmp, 'frontend'))

  // Raíz permitida para el navegador de carpetas y las subidas (US-026).
  const raizSubidas = path.join(raizTmp, 'archivos')
  fs.mkdirSync(raizSubidas, { recursive: true })

  // --- Servidor de tmux propio, por socket ---
  const socketTmux = `muxspace-e2e-${crypto.randomBytes(4).toString('hex')}`
  const wrapperTmux = path.join(raizTmp, 'tmux')
  fs.writeFileSync(
    wrapperTmux,
    [
      '#!/bin/sh',
      // El E2E puede lanzarse desde DENTRO de una sesión de tmux del usuario, y
      // esa variable apunta a su socket. `-L` ya gana, pero dejarla puesta es
      // dejar un puntero al servidor equivocado.
      'unset TMUX',
      `TMUX_TMPDIR=${JSON.stringify(raizTmp)}`,
      'export TMUX_TMPDIR',
      `exec tmux -L ${socketTmux} "$@"`,
    ].join('\n') + '\n',
    { mode: 0o755 },
  )

  // --- Credenciales y puerto ---
  const usuario = 'e2e'
  // Generada, no escrita a mano: si esta contraseña se colara en un log o en
  // una captura, no serviría para nada en ningún otro sitio.
  const password = crypto.randomBytes(24).toString('base64url')
  const puerto = await puertoLibre()
  if (puerto === 8000) throw new Error('el sistema dio el 8000; reintenta')
  const baseURL = `http://127.0.0.1:${puerto}`

  const log = fs.openSync(path.join(DIR_TMP, 'backend.log'), 'w')
  const proceso = spawn(
    PYTHON,
    [
      '-m',
      'uvicorn',
      'main:app',
      '--app-dir',
      backendTmp,
      '--host',
      '127.0.0.1',
      '--port',
      String(puerto),
      // El panel solo admite un worker (US-023); el E2E arranca como producción.
      '--workers',
      '1',
    ],
    {
      cwd: raizTmp,
      stdio: ['ignore', log, log],
      env: {
        ...process.env,
        MUXSPACE_AUTH_ENABLED: 'true',
        MUXSPACE_AUTH_MODE: 'env',
        MUXSPACE_USERNAME: usuario,
        MUXSPACE_PASSWORD: password,
        // Obligatorio false: el E2E habla http://127.0.0.1 y el navegador no
        // guarda una cookie marcada `Secure` por HTTP. Con el default de
        // producción (true) el login devolvería 200 y la siguiente petición 401.
        MUXSPACE_COOKIE_SECURE: 'false',
        MUXSPACE_HOST: '127.0.0.1',
        MUXSPACE_PORT: String(puerto),
        MUXSPACE_CORS_ORIGINS: baseURL,
        MUXSPACE_TMUX_BINARY: wrapperTmux,
        MUXSPACE_DIR_SUGGESTION_ROOTS: JSON.stringify([raizSubidas]),
        MUXSPACE_DOCS_ENABLED: 'false',
        // Que un `.env` del usuario no se cuele por la puerta de atrás.
        MUXSPACE_ENV_FILE: path.join(raizTmp, 'no-existe.env'),
        WEB_CONCURRENCY: '1',
      },
    },
  )
  proceso.unref()

  // El pid, dentro del propio temporal: es lo que permite a una ejecución
  // futura distinguir "resto de algo que murió" de "otra ejecución en marcha".
  fs.writeFileSync(path.join(raizTmp, 'backend.pid'), String(proceso.pid))

  await esperarA(`${baseURL}/api/health`, 30000, proceso)

  guardarEntorno({
    baseURL,
    puerto,
    usuario,
    password,
    pid: proceso.pid,
    raizTmp,
    backendTmp,
    wrapperTmux,
    socketTmux,
    raizSubidas,
  })

  // Comprobación de aislamiento, antes de que corra ningún test: se crea una
  // sesión por el wrapper y se verifica que NO aparece en el servidor de tmux
  // del usuario. No es "el atributo vale lo que le puse": es el efecto.
  const canario = `muxspace-e2e-canario-${crypto.randomBytes(3).toString('hex')}`
  execFileSync(wrapperTmux, ['new-session', '-d', '-s', canario])
  let delUsuario = ''
  try {
    delUsuario = execFileSync('tmux', ['list-sessions', '-F', '#S'], {
      encoding: 'utf8',
    })
  } catch {
    // "no server running": el usuario no tiene tmux abierto. Mejor todavía.
  }
  if (delUsuario.includes(canario)) {
    execFileSync('tmux', ['kill-session', '-t', canario])
    throw new Error(
      'AISLAMIENTO ROTO: la sesión de prueba ha aparecido en el servidor de ' +
        'tmux del usuario. No puede correr ningún test en estas condiciones.',
    )
  }
  execFileSync(wrapperTmux, ['kill-session', '-t', canario])

  console.log(`[e2e] backend de pruebas en ${baseURL} (pid ${proceso.pid})`)
  console.log(`[e2e] datos y tmux aislados en ${raizTmp}`)
}
