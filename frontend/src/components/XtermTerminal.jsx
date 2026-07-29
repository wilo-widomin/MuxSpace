import React, { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useT } from '../i18n/index.jsx'

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
// Con el `mouse` de tmux en off, arrastrar selecciona nativo en xterm y la
// rueda hace scroll del scrollback propio. Si el usuario prefiere el scroll
// nativo de tmux (mouse on), seleccionar con Shift+arrastrar sigue copiando.
export default function XtermTerminal({ name, onFocus, focusToken = 0 }) {
  const containerRef = useRef(null)
  // Referencia a la instancia de xterm para poder darle el foco de teclado
  // de forma imperativa (p. ej. al abrir un proyecto/comando desde el panel).
  const termRef = useRef(null)
  const { t } = useT()
  // El efecto no depende del idioma (recrear la terminal al cambiarlo
  // perdería el scrollback), así que lee la traducción por ref en el
  // momento de escribirla en pantalla.
  const tRef = useRef(t)
  tRef.current = t

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

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    }

    // Al conectar, reajusta y manda el tamaño real: así tmux redibuja la
    // sesión con las dimensiones del tile en vez de las 80x24 por defecto.
    ws.onopen = () => refit()
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') term.write(ev.data)
      else term.write(new Uint8Array(ev.data))
    }
    ws.onclose = () => {
      // Los escapes ANSI (atenuado / reset) quedan FUERA de la clave: solo
      // el literal es traducible.
      term.write(`\r\n\x1b[2m${tRef.current('term.disconnected')}\x1b[0m\r\n`)
    }

    const dataDisp = term.onData((d) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(enc.encode(d))
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
      ro.disconnect()
      container.removeEventListener('mouseup', copySelection)
      container.removeEventListener('contextmenu', onContextMenu)
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

  return (
    <div
      ref={containerRef}
      onMouseDown={onFocus}
      className="h-full w-full overflow-hidden"
      style={{ background: '#000000' }}
    />
  )
}
