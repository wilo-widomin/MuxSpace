import { useEffect, useRef, useState } from 'react'

import { useT } from '../i18n/index.jsx'
import { LinkIcon } from './sidebar/icons.jsx'

/**
 * Botón de enlaces del panel, con su lista colgando.
 *
 * Vive en la cabecera del sidebar, junto al cronómetro y al dashboard, y no
 * en la de cada terminal: son enlaces del panel entero, los mismos mires la
 * sesión que mires, y repetir el botón en cada tile era repetir el mismo
 * menú tantas veces como ventanas hubiera abiertas.
 *
 * El menú cuelga alineado a la izquierda del icono y se abre hacia la
 * derecha, tanto con el sidebar plegado (`compacto`) como desplegado. Abrirlo
 * hacia la izquierda con el sidebar desplegado lo dejaba encima del logo y
 * medio fuera de la barra, y no se leía.
 */
export function WebLinksMenu({ links = [], compacto = false }) {
  const { t } = useT()
  const [abierto, setAbierto] = useState(false)
  const cajaRef = useRef(null)

  // Escape y clic fuera cierran. Sin lo segundo, el menú se quedaba abierto
  // al ir a pulsar otra cosa del sidebar y tapaba justo lo que se buscaba.
  useEffect(() => {
    if (!abierto) return undefined
    const alPulsar = (e) => {
      if (e.key === 'Escape') setAbierto(false)
    }
    const fuera = (e) => {
      if (!cajaRef.current?.contains(e.target)) setAbierto(false)
    }
    window.addEventListener('keydown', alPulsar, true)
    document.addEventListener('mousedown', fuera)
    return () => {
      window.removeEventListener('keydown', alPulsar, true)
      document.removeEventListener('mousedown', fuera)
    }
  }, [abierto])

  return (
    <div ref={cajaRef} className={compacto ? 'relative mt-2' : 'relative'}>
      <button
        onClick={() => setAbierto((a) => !a)}
        title={t('links.title')}
        aria-label={t('links.title')}
        aria-expanded={abierto}
        className={`rounded text-panel-muted transition hover:bg-panel-bg hover:text-gray-100 ${
          compacto ? 'p-1.5' : 'p-1'
        }`}
      >
        <LinkIcon />
      </button>
      {abierto && (
        <div
          className="absolute left-0 top-full z-40 mt-1 max-h-64 w-56 overflow-y-auto rounded border border-panel-border bg-panel-surface shadow-lg"
        >
          <ul>
            {links.map((x) => (
              <li key={x.id}>
                <a
                  href={x.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={() => setAbierto(false)}
                  className="block truncate px-2 py-1.5 text-xs text-panel-muted hover:bg-panel-bg hover:text-gray-100"
                  title={x.url}
                >
                  {x.title}
                </a>
              </li>
            ))}
            {links.length === 0 && (
              <li className="px-2 py-1.5 text-xs text-panel-muted">
                {t('links.empty')}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
