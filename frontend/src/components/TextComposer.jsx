import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useT } from '../i18n/index.jsx'

// Redactor de textos largos, sobre la terminal.
//
// POR QUÉ EXISTE: en una TUI como Claude Code, Enter envía. Escribir un
// mensaje de varios párrafos ahí dentro es imposible sin mandarlo a trozos, y
// la alternativa —irse a un editor, escribir, volver, pegar— saca al usuario
// de la ventana. Aquí Enter es un salto de línea y nada más.
//
// Al cerrar, el texto queda en el portapapeles: es lo que se esperaba haber
// hecho a mano, así que hacerlo solo evita el "lo escribí y lo perdí".
//
// El borrador se guarda POR SESIÓN mientras se escribe. Cerrar sin querer un
// texto de veinte líneas es un accidente barato de evitar y caro de sufrir.

const CLAVE_BORRADOR = 'muxspace:composer:'

export default function TextComposer({ name, onClose, onPaste }) {
  const { t } = useT()
  const [texto, setTexto] = useState(
    () => localStorage.getItem(CLAVE_BORRADOR + name) || ''
  )
  const [copiado, setCopiado] = useState(false)
  const areaRef = useRef(null)
  // El texto vive también en un ref para que el cierre pueda copiarlo sin
  // volver a suscribir el efecto de desmontaje a cada tecla.
  const textoRef = useRef(texto)
  textoRef.current = texto

  useEffect(() => {
    areaRef.current?.focus()
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(CLAVE_BORRADOR + name, texto)
    } catch {
      /* sin sitio para el borrador: se sigue pudiendo escribir */
    }
  }, [name, texto])

  const copiar = useCallback(async () => {
    const contenido = textoRef.current
    if (!contenido || !navigator.clipboard) return false
    try {
      await navigator.clipboard.writeText(contenido)
      return true
    } catch {
      return false
    }
  }, [])

  const cerrar = useCallback(async () => {
    await copiar()
    onClose()
  }, [copiar, onClose])

  const copiarSinCerrar = useCallback(async () => {
    if (await copiar()) {
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1500)
    }
  }, [copiar])

  const pegar = useCallback(() => {
    if (!textoRef.current) return
    onPaste(textoRef.current)
    onClose()
  }, [onPaste, onClose])

  const onTecla = useCallback(
    (e) => {
      // Enter es un salto de línea: es justamente lo que no se puede hacer en
      // la terminal y la razón de que esto exista. Solo Esc cierra.
      if (e.key === 'Escape') {
        e.preventDefault()
        cerrar()
      }
      // Las pulsaciones no deben llegar a la terminal de detrás.
      e.stopPropagation()
    },
    [cerrar]
  )

  return (
    <div className="absolute inset-0 z-40 flex flex-col bg-panel-bg">
      <div className="flex items-center gap-2 border-b border-panel-border bg-panel-surface px-3 py-2">
        <span className="truncate text-xs text-panel-muted">
          {t('compose.title', { name })}
        </span>
        <span className="ml-auto text-xs text-panel-muted">
          {t('compose.chars', { count: texto.length })}
        </span>
        <button
          type="button"
          onClick={pegar}
          disabled={!texto}
          className="rounded border border-panel-accent px-2 py-0.5 text-xs text-gray-100 transition hover:bg-panel-accent/20 disabled:opacity-40"
        >
          {t('compose.paste')}
        </button>
        <button
          type="button"
          onClick={copiarSinCerrar}
          disabled={!texto}
          className="rounded border border-panel-border px-2 py-0.5 text-xs text-panel-muted transition hover:text-gray-100 disabled:opacity-40"
        >
          {copiado ? t('compose.copied') : t('compose.copy')}
        </button>
        <button
          type="button"
          onClick={cerrar}
          title={t('compose.close')}
          className="px-1 text-sm text-panel-muted hover:text-gray-100"
        >
          ×
        </button>
      </div>

      <textarea
        ref={areaRef}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        onKeyDown={onTecla}
        placeholder={t('compose.placeholder')}
        className="min-h-0 flex-1 resize-none bg-panel-bg px-3 py-2 font-mono text-sm leading-relaxed text-gray-100 placeholder:text-panel-muted outline-none"
      />
    </div>
  )
}
