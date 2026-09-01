import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useT } from '../i18n/index.jsx'
import TranscriptSearch from './TranscriptSearch.jsx'

// Terminal propia basada en xterm.js, conectada por WebSocket al puente PTY
// del backend (`/api/terminal/{name}` -> `tmux attach`). Reemplaza al iframe
// de ttyd para poder controlar la copia al portapapeles nosotros mismos:
//
//   - Copiar al SELECCIONAR con el ratón (navigator.clipboard, funciona en
//     contexto seguro — confirmado isSecureContext:true en este despliegue).
//   - Cmd/Ctrl+C copia la selección; Cmd/Ctrl+V y clic derecho pegan.
//   - Handler OSC 52: si una app dentro de tmux (vim, etc.) fija el
//     portapapeles, también llega al del sistema.
//
// SCROLL: tmux ocupa la pantalla alternativa, así que el scrollback propio de
// xterm está SIEMPRE vacío — el historial vive dentro de tmux. Por eso la
// rueda no movía nada y no había barra. Aquí la rueda y la barra que pintamos
// se traducen a órdenes de copy-mode que ejecuta el backend (mensajes
// `scroll` / `scroll-to` por el mismo WebSocket), y tmux nos devuelve la
// posición en un `scroll-state`.
//
// Lo que NO se hace es poner el `mouse` de tmux en on, que sería la solución
// obvia: con el ratón capturado por tmux, arrastrar deja de crear una
// selección de xterm y el copiar-al-seleccionar de arriba se rompe.
export default function XtermTerminal({
  name,
  onFocus,
  onActivity,
  focusToken = 0,
  searchToken = 0,
  pasteRequest = null,
}) {
  const containerRef = useRef(null)
  // Posición dentro del historial de tmux, tal cual la reporta el backend:
  // `position` son líneas subidas desde el final (0 = en vivo), `history` el
  // total guardado y `height` las filas visibles del panel.
  const [scroll, setScroll] = useState({ position: 0, history: 0, height: 0 })
  // El WebSocket, para que la barra (fuera del efecto) pueda mandar por él.
  const wsRef = useRef(null)
  // ¿El programa del panel ocupa su PROPIA pantalla alternativa (Claude Code,
  // vim, less…)? En ese caso no hay historial en tmux y el scroll lo hace el
  // programa: la rueda tiene que llegarle, no la interceptamos. En un ref
  // porque la lee el manejador de la rueda, que vive dentro del efecto.
  const alternateRef = useRef(false)
  // Distinto de null mientras se arrastra la barra: guarda dónde se agarró el
  // tirador. Lo mira también el WebSocket, para no pisar con una posición ya
  // vieja de tmux la que el usuario está eligiendo con el ratón.
  const arrastreRef = useRef(null)
  // Texto de la caja de búsqueda; `null` = cerrada. La búsqueda la resuelve
  // el copy-mode de tmux (ver `_buscar` en el backend), no xterm.js: su
  // buffer está vacío y el resaltado de coincidencias ya lo pinta tmux.
  const [busqueda, setBusqueda] = useState(null)
  // Coincidencias de la última búsqueda; `null` = aún no se ha buscado. tmux
  // no dice si encontró algo, así que sin esto "no está" y "está pero no lo
  // has visto" se ven exactamente igual.
  const [coincidencias, setCoincidencias] = useState(null)
  // Modal con la conversación de Claude (solo en paneles en pantalla
  // alternativa, donde no hay historial de tmux que buscar).
  const [transcript, setTranscript] = useState(false)
  // Espejo en un ref: la lupa funciona como interruptor y su efecto solo
  // depende del contador, así que necesita leer el estado sin re-suscribirse.
  const transcriptRef = useRef(false)
  transcriptRef.current = transcript
  const inputBusquedaRef = useRef(null)
  // Referencia a la instancia de xterm para poder darle el foco de teclado
  // de forma imperativa (p. ej. al abrir un proyecto/comando desde el panel).
  const termRef = useRef(null)
  const { t } = useT()
  // El efecto no depende del idioma (recrear la terminal al cambiarlo
  // perdería el scrollback), así que lee la traducción por ref en el
  // momento de escribirla en pantalla.
  const tRef = useRef(t)
  tRef.current = t
  // Ref espejo, por lo mismo que `tRef`: el efecto principal depende SOLO de
  // `[name]`, y meter aquí un callback del padre recrearía la terminal y su
  // WebSocket en cada render de arriba.
  const onActivityRef = useRef(onActivity)
  onActivityRef.current = onActivity

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 13,
      scrollback: 10000,
      allowProposedApi: true,
      theme: { background: '#000000', foreground: '#e5e7eb' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    termRef.current = term

    const enc = new TextEncoder()

    // Reajusta filas/columnas al tamaño real del contenedor y avisa a tmux.
    // Definido pronto porque lo usan varios disparadores (fuente lista,
    // WebSocket abierto, ResizeObserver) para cubrir el momento exacto en
    // que el layout queda estable y xterm puede ocupar todo el div.
    const refit = () => {
      try {
        fit.fit()
        sendResize()
      } catch {
        /* el contenedor aún no tiene tamaño; se reintenta al reaparecer */
      }
    }

    // Al arrastrar un separador del grid el ResizeObserver dispara en cada
    // frame; sin agrupar, eso serían ~60 fit() y ~60 mensajes `resize` por
    // segundo y por terminal, y tmux redibujaría la sesión en cada uno.
    // Reajustamos una sola vez cuando el tamaño se estabiliza.
    let refitTimer = null
    const refitSoon = () => {
      if (refitTimer) clearTimeout(refitTimer)
      refitTimer = setTimeout(refit, 60)
    }

    // ---- Copia al portapapeles del sistema ----
    const copySelection = () => {
      const sel = term.getSelection()
      if (sel && navigator.clipboard) {
        navigator.clipboard.writeText(sel).catch(() => {})
      }
    }
    // Copiar al terminar un arrastre de selección (equivale a copyOnSelect).
    container.addEventListener('mouseup', copySelection)

    // ---- Pegar ----
    const doPaste = () => {
      if (navigator.clipboard) {
        navigator.clipboard
          .readText()
          .then((text) => {
            if (text) term.paste(text)
          })
          .catch(() => {})
      }
    }
    const onContextMenu = (e) => {
      e.preventDefault()
      doPaste()
    }
    container.addEventListener('contextmenu', onContextMenu)

    // ---- OSC 52: apps dentro de tmux que fijan el portapapeles ----
    term.parser.registerOscHandler(52, (payload) => {
      // Formato: "<selección>;<base64>" (p. ej. "c;SGVsbG8=").
      const b64 = payload.slice(payload.indexOf(';') + 1)
      try {
        // atob() devuelve una "binary string": cada carácter es UN byte (0-255),
        // o sea los bytes interpretados como Latin-1. Pero tmux codifica el texto
        // en UTF-8, así que hay que reconstruir los bytes y decodificarlos como
        // UTF-8; si no, "había" llega al portapapeles como "habÃ­a" (mojibake).
        const binary = atob(b64)
        const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0))
        const text = new TextDecoder('utf-8').decode(bytes)
        if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {})
      } catch {
        /* base64 inválido: ignorar */
      }
      return true
    })

    // ---- Atajos de teclado (copiar/pegar) ----
    term.attachCustomKeyEventHandler((e) => {
      if (e.type !== 'keydown') return true
      const mod = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()
      if (mod && key === 'c' && term.hasSelection()) {
        copySelection()
        return false // no mandar ^C al terminal cuando hay selección
      }
      // Ctrl/Cmd+F abre la búsqueda del historial. En pantalla alternativa NO
      // se intercepta: ahí no hay historial de tmux que buscar y la tecla es
      // del programa (en Claude Code, en vim…), no nuestra.
      if (mod && key === 'f') {
        // `preventDefault` explícito: devolver false solo evita que xterm
        // procese la tecla, pero el navegador la sigue viendo y abría SU
        // buscador encima del nuestro.
        e.preventDefault()
        if (alternateRef.current) {
          // Programa en su propia pantalla (Claude Code): tmux no guarda nada
          // de lo que pinta, así que aquí se busca en el transcript de la
          // conversación, en un modal. Ver TranscriptSearch.jsx.
          setTranscript(true)
        } else {
          setBusqueda((actual) => (actual === null ? '' : actual))
        }
        return false
      }
      // Shift+Enter = salto de línea sin enviar. Un terminal manda `\r` tanto
      // con Enter como con Shift+Enter, así que Claude Code (u opencode) no
      // puede distinguirlos y obligan a Ctrl+J. Mandando ESC+CR —lo mismo que
      // configura `/terminal-setup` en iTerm2 o VSCode— sí lo reconocen como
      // nueva línea. En una shell normal es inofensivo: se trata como Enter.
      if (e.key === 'Enter' && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const sock = wsRef.current
        if (sock && sock.readyState === WebSocket.OPEN) sock.send(enc.encode('\x1b\r'))
        onActivityRef.current?.()
        return false
      }
      // OJO: no interceptamos Ctrl/Cmd+V. xterm.js ya gestiona el pegado
      // nativo del navegador sobre su textarea oculto; si además llamáramos
      // aquí a doPaste() el texto se pegaría DOS veces. El pegado con el botón
      // derecho sí usa doPaste() (en `contextmenu`), porque ahí no hay evento
      // de pegado nativo.
      return true
    })

    // ---- WebSocket hacia el puente PTY ----
    // Autenticación: la cookie de sesión HttpOnly viaja sola en el
    // handshake; la URL no lleva ninguna credencial.
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url =
      `${proto}://${window.location.host}/api/terminal/` + encodeURIComponent(name)
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const enviarControl = (msg) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
    }

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }

    // Al conectar, reajusta y manda el tamaño real: así tmux redibuja la
    // sesión con las dimensiones del tile en vez de las 80x24 por defecto.
    ws.onopen = () => {
      refit()
      enviarControl({ type: 'scroll-query' })
    }
    ws.onmessage = (ev) => {
      // Los bytes del terminal llegan SIEMPRE en frames binarios; los de
      // texto son el canal de control del backend (hoy, la posición del
      // historial). Así no hay forma de confundir salida con estado.
      if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data)
          if (msg.type === 'search-result') {
            setCoincidencias(msg.matches || 0)
            return
          }
          if (msg.type === 'scroll-state') {
            alternateRef.current = Boolean(msg.alternate)
            // Mientras se arrastra manda el ratón: un estado en vuelo, pedido
            // antes del último movimiento, haría saltar el tirador hacia atrás.
            if (arrastreRef.current !== null) return
            setScroll({
              // En pantalla alternativa no hay historial que ofrecer, así que
              // la barra no debe aparecer aunque tmux guarde líneas de antes
              // de arrancar el programa.
              position: msg.alternate ? 0 : msg.position || 0,
              history: msg.alternate ? 0 : msg.history || 0,
              height: msg.height || 0,
            })
          }
        } catch {
          /* control mal formado: ignorar, nunca escribirlo en pantalla */
        }
        return
      }
      term.write(new Uint8Array(ev.data))
    }
    ws.onclose = () => {
      // Los escapes ANSI (atenuado / reset) quedan FUERA de la clave: solo
      // el literal es traducible.
      term.write(`\r\n\x1b[2m${tRef.current('term.disconnected')}\x1b[0m\r\n`)
    }

    // ---- Rueda del ratón -> historial de tmux ----
    // Se escucha en CAPTURA para adelantarse al manejador propio de xterm:
    // en pantalla alternativa xterm traduciría la rueda a flechas, que en un
    // shell significan "comando anterior". Eso no es scroll, es un accidente.
    //
    // Los eventos llegan a decenas por segundo y cada uno acaba en un
    // `tmux send-keys`, así que se acumulan y se mandan agrupados.
    let lineasPendientes = 0
    let scrollTimer = null
    const enviarScroll = () => {
      scrollTimer = null
      const lineas = Math.trunc(lineasPendientes)
      lineasPendientes -= lineas
      if (lineas) enviarControl({ type: 'scroll', lines: lineas })
    }
    const onWheel = (e) => {
      // Programa en pantalla alternativa (Claude Code, vim, less…): la rueda
      // es suya. xterm.js la traduce a flechas y el programa scrollea su
      // propio buffer, que es como funcionaba antes de existir esto y lo
      // único que puede funcionar ahí: tmux no guarda nada de esas pantallas.
      if (alternateRef.current) return
      e.preventDefault()
      e.stopPropagation()
      // deltaMode 1 = líneas, 2 = páginas; 0 = píxeles (lo normal).
      const alturaFila =
        term.element?.querySelector('.xterm-rows > div')?.offsetHeight || 17
      const factor =
        e.deltaMode === 1 ? 1 : e.deltaMode === 2 ? term.rows : 1 / alturaFila
      // Hacia arriba (deltaY negativo) es ir hacia el historial: positivo.
      lineasPendientes -= e.deltaY * factor
      if (!scrollTimer) scrollTimer = setTimeout(enviarScroll, 40)
    }
    container.addEventListener('wheel', onWheel, { capture: true, passive: false })

    // El tamaño del historial crece con cada línea que imprime el programa, y
    // el backend solo nos informa cuando hay un gesto. Mientras el puntero
    // está encima —o sea, cuando la barra se está mirando— se refresca sola.
    let hover = false
    const onEnter = () => {
      hover = true
      enviarControl({ type: 'scroll-query' })
    }
    const onLeave = () => {
      hover = false
    }
    container.addEventListener('mouseenter', onEnter)
    container.addEventListener('mouseleave', onLeave)
    const sondeo = setInterval(() => {
      if (hover) enviarControl({ type: 'scroll-query' })
    }, 2000)

    const dataDisp = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(enc.encode(d))
      // Escribir en la terminal es la forma más clara de atenderla. El padre
      // corta enseguida si no había marca: aquí no se sabe si la hay, y
      // consultarlo obligaría a meter ese estado en las dependencias.
      onActivityRef.current?.()
    })

    // ---- Ajuste de tamaño ----
    // fit() necesita que el layout y la fuente estén listos para medir bien
    // la celda; disparamos en el frame siguiente y cuando la fuente carga,
    // además del ResizeObserver para cualquier cambio de tamaño posterior.
    const raf = requestAnimationFrame(refit)
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(refit).catch(() => {})
    }
    const ro = new ResizeObserver(() => refitSoon())
    ro.observe(container)

    return () => {
      cancelAnimationFrame(raf)
      if (refitTimer) clearTimeout(refitTimer)
      if (scrollTimer) clearTimeout(scrollTimer)
      clearInterval(sondeo)
      ro.disconnect()
      container.removeEventListener('mouseup', copySelection)
      container.removeEventListener('contextmenu', onContextMenu)
      container.removeEventListener('wheel', onWheel, { capture: true })
      container.removeEventListener('mouseenter', onEnter)
      container.removeEventListener('mouseleave', onLeave)
      wsRef.current = null
      dataDisp.dispose()
      try {
        ws.close()
      } catch {
        /* ya cerrado */
      }
      termRef.current = null
      term.dispose()
    }
  }, [name])

  // Foco imperativo: cuando el padre incrementa `focusToken` (al abrir un
  // proyecto/comando en esta terminal), le damos el foco de teclado para que
  // se pueda escribir de inmediato sin tener que hacer clic en ella.
  useEffect(() => {
    if (focusToken) termRef.current?.focus()
  }, [focusToken])

  // Texto que llega del redactor. Se usa `term.paste()` y no un `write` de los
  // bytes: paste envuelve el texto en el pegado con corchetes cuando el
  // programa lo pide, y eso es lo que hace que una TUI trate veinte líneas
  // como UN pegado en vez de como veinte pulsaciones de Enter.
  const pasteToken = pasteRequest?.token || 0
  const pasteTextoRef = useRef('')
  pasteTextoRef.current = pasteRequest?.text || ''
  useEffect(() => {
    if (!pasteToken) return
    const term = termRef.current
    if (!term || !pasteTextoRef.current) return
    term.focus()
    term.paste(pasteTextoRef.current)
  }, [pasteToken])

  // La lupa del tile: mismo criterio que Ctrl+F (en pantalla alternativa no
  // hay historial de tmux, así que se abre la conversación de Claude), pero
  // funciona como INTERRUPTOR — el mismo botón que abre, cierra. En una
  // tableta no hay Esc, así que dejar solo el abrir sería una puerta sin
  // pomo por dentro.
  useEffect(() => {
    if (!searchToken) return
    if (alternateRef.current) {
      if (transcriptRef.current) {
        setTranscript(false)
        termRef.current?.focus()
      } else {
        setTranscript(true)
      }
      return
    }
    setBusqueda((actual) => {
      if (actual !== null) {
        // Cerrar equivale a pulsar Esc: hay que salir del copy-mode para que
        // el panel vuelva al final, donde se escribe.
        setCoincidencias(null)
        const ws = wsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'scroll-exit' }))
        }
        termRef.current?.focus()
        return null
      }
      return ''
    })
  }, [searchToken])

  // ---- Barra de scroll propia ----
  // No puede ser la nativa de xterm (su viewport no tiene contenido: el
  // historial está en tmux), así que se pinta encima y se traduce el arrastre
  // a una posición absoluta del historial.
  const trackRef = useRef(null)
  const { position, history, height } = scroll
  const total = history + height
  const hayHistorial = history > 0 && height > 0
  // Fracción visible y desplazamiento del pulgar. `position` cuenta líneas
  // subidas desde el final, así que 0 deja el pulgar abajo del todo.
  const altoPulgar = hayHistorial ? Math.max(0.04, height / total) : 0
  // Cuánto del recorrido se ha bajado: 0 = arriba del todo, 1 = en vivo.
  const topePulgar = hayHistorial ? (history - position) / history : 1

  // Envío del salto: el tirador NO espera a tmux. Se mueve en el acto con la
  // posición local y los mensajes salen como mucho cada 100 ms, quedándose
  // siempre con el último. Mandar uno por `pointermove` era un repintado
  // completo del panel por cada píxel: el arrastre iba a tirones.
  const envioRef = useRef({ timer: null, pendiente: null })
  const irA = useCallback((posicion) => {
    const destino = Math.round(posicion)
    // Optimista: la barra responde al ratón aunque tmux tarde en confirmar.
    setScroll((s) => ({ ...s, position: destino }))

    const envio = envioRef.current
    const mandar = () => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'scroll-to', position: envio.pendiente }))
      }
      envio.pendiente = null
      envio.timer = setTimeout(() => {
        envio.timer = null
        if (envio.pendiente !== null) mandar()
      }, 100)
    }
    envio.pendiente = destino
    if (!envio.timer) mandar()
  }, [])

  const posicionDesdeRaton = useCallback(
    (clientY, agarre) => {
      const track = trackRef.current
      if (!track) return 0
      const rect = track.getBoundingClientRect()
      const alto = rect.height * altoPulgar
      // `agarre` es dónde se pinchó DENTRO del pulgar; sin él, arrastrar daría
      // un salto inicial del tamaño del pulgar.
      const top = clientY - rect.top - agarre
      const libre = Math.max(1, rect.height - alto)
      const fraccion = Math.min(1, Math.max(0, top / libre))
      // Arriba del todo = toda la historia por encima; abajo = en vivo.
      return history - fraccion * history
    },
    [altoPulgar, history],
  )

  const onPulgarDown = useCallback(
    (e) => {
      e.preventDefault()
      e.stopPropagation()
      const track = trackRef.current
      if (!track) return
      const rect = track.getBoundingClientRect()
      const alto = rect.height * altoPulgar
      const topActual = topePulgar * (rect.height - alto)
      const dentroDelPulgar = e.currentTarget.dataset.rol === 'thumb'
      // Pinchar en la pista mueve el pulgar a ese punto (agarre = su centro);
      // pinchar en el pulgar lo arrastra desde donde se cogió.
      const agarre = dentroDelPulgar ? e.clientY - rect.top - topActual : alto / 2
      arrastreRef.current = agarre
      if (!dentroDelPulgar) irA(posicionDesdeRaton(e.clientY, agarre))
      e.currentTarget.setPointerCapture?.(e.pointerId)
    },
    [altoPulgar, topePulgar, irA, posicionDesdeRaton],
  )

  const onPulgarMove = useCallback(
    (e) => {
      if (arrastreRef.current === null) return
      irA(posicionDesdeRaton(e.clientY, arrastreRef.current))
    },
    [irA, posicionDesdeRaton],
  )

  const enviarWs = useCallback((msg) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
  }, [])

  const onPulgarUp = useCallback(
    (e) => {
      arrastreRef.current = null
      e.currentTarget.releasePointerCapture?.(e.pointerId)
      // Al soltar, la verdad vuelve a ser la de tmux: puede haber recortado el
      // salto (el historial cambia mientras el programa escribe).
      enviarWs({ type: 'scroll-query' })
    },
    [enviarWs],
  )

  // ---- Búsqueda en el historial ----
  const buscando = busqueda !== null

  const buscar = useCallback(
    (direccion) => {
      if (!busqueda) return
      enviarWs({ type: 'search', text: busqueda, direction: direccion })
      // La búsqueda mueve el copy-mode: que la barra refleje dónde ha caído.
      enviarWs({ type: 'scroll-query' })
    },
    [busqueda, enviarWs],
  )

  const cerrarBusqueda = useCallback(() => {
    setBusqueda(null)
    setCoincidencias(null)
    // Salir del copy-mode devuelve el panel al final, que es donde el usuario
    // espera estar para seguir escribiendo.
    enviarWs({ type: 'scroll-exit' })
    termRef.current?.focus()
  }, [enviarWs])

  const onTeclaBusqueda = useCallback(
    (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        // Enter va hacia atrás (lo más reciente primero), como en cualquier
        // historial; Mayús+Enter deshace el camino.
        buscar(e.shiftKey ? 'down' : 'up')
      } else if (e.key === 'Escape') {
        e.preventDefault()
        cerrarBusqueda()
      }
    },
    [buscar, cerrarBusqueda],
  )

  useEffect(() => {
    if (buscando) inputBusquedaRef.current?.focus()
  }, [buscando])

  // El temporizador del envío agrupado sobrevive al desmontaje si no se para.
  useEffect(() => {
    const envio = envioRef.current
    return () => {
      if (envio.timer) clearTimeout(envio.timer)
      envio.timer = null
      envio.pendiente = null
    }
  }, [])

  return (
    <div className="relative h-full w-full" style={{ background: '#000000' }}>
      <div
        ref={containerRef}
        onMouseDown={onFocus}
        className="h-full w-full overflow-hidden"
        style={{ background: '#000000' }}
      />
      {transcript && (
        <TranscriptSearch
          name={name}
          onClose={() => {
            setTranscript(false)
            termRef.current?.focus()
          }}
        />
      )}
      {buscando && (
        // Va por encima de todo (xterm apila hasta z-index 10) y a la
        // izquierda de la barra, para no taparla.
        // Borde de acento y un halo: sobre el fondo negro de la terminal, una
        // caja con el borde gris del panel se pierde y el usuario no la ve.
        <div className="absolute right-4 top-1 z-30 flex items-center gap-1 rounded border border-panel-accent bg-panel-surface px-2 py-1 shadow-lg ring-1 ring-panel-accent/40">
          <input
            ref={inputBusquedaRef}
            type="text"
            value={busqueda}
            onChange={(e) => {
              setBusqueda(e.target.value)
              // Lo contado ya no vale para el texto nuevo: mejor nada que un
              // número que engaña.
              setCoincidencias(null)
            }}
            onKeyDown={onTeclaBusqueda}
            placeholder={t('term.search_placeholder')}
            className="w-48 bg-transparent text-xs text-gray-100 placeholder:text-panel-muted outline-none"
          />
          {coincidencias !== null && (
            <span
              className={`whitespace-nowrap text-xs ${
                coincidencias ? 'text-panel-muted' : 'text-red-400'
              }`}
            >
              {coincidencias
                ? t('term.search_matches', { count: coincidencias })
                : t('term.search_none')}
            </span>
          )}
          <button
            type="button"
            onClick={() => buscar('up')}
            title={t('term.search_prev')}
            className="px-1 text-xs text-panel-muted hover:text-gray-100"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => buscar('down')}
            title={t('term.search_next')}
            className="px-1 text-xs text-panel-muted hover:text-gray-100"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={cerrarBusqueda}
            title={t('term.search_close')}
            className="px-1 text-xs text-panel-muted hover:text-gray-100"
          >
            ×
          </button>
        </div>
      )}
      {hayHistorial && (
        <div
          ref={trackRef}
          data-rol="track"
          // `z-20` no es decorativo: xterm.js apila sus capas hasta z-index 10
          // (xterm.css), así que sin esto la barra queda DEBAJO del terminal —
          // invisible y sorda a los clics.
          className="absolute right-0 top-0 bottom-0 z-20 w-2.5 cursor-pointer"
          onPointerDown={onPulgarDown}
          onPointerMove={onPulgarMove}
          onPointerUp={onPulgarUp}
          onPointerCancel={onPulgarUp}
        >
          <div
            data-rol="thumb"
            className="absolute right-0.5 w-1.5 rounded-full bg-slate-400/40 hover:bg-slate-300/70"
            style={{
              height: `${altoPulgar * 100}%`,
              top: `calc(${topePulgar * 100}% - ${topePulgar * altoPulgar * 100}%)`,
            }}
            onPointerDown={onPulgarDown}
            onPointerMove={onPulgarMove}
            onPointerUp={onPulgarUp}
            onPointerCancel={onPulgarUp}
          />
        </div>
      )}
    </div>
  )
}
