import { useT } from '../i18n/index.jsx'
import { LanguagePicker } from './LanguagePicker.jsx'
import { Modal } from './sidebar/Modal.jsx'
import { BellIcon, BoltIcon, LinkIcon } from './sidebar/icons.jsx'

/**
 * Menú de ajustes del panel: la puerta única a las preferencias que no son
 * de una sesión concreta.
 *
 * Sustituye a la campanilla que estaba suelta en el pie. Con dos ajustes ya
 * no cabían dos iconos ahí, y el tercero tampoco cabría: el pie es estrecho
 * por definición, así que crece el menú y no la fila de botones.
 *
 * Cada fila es alta a propósito: esto se usa desde una tableta, donde el
 * objetivo de un dedo no puede medir lo mismo que el de un ratón.
 *
 * El idioma es la excepción a "una fila, un diálogo": es un desplegable de
 * seis opciones y abrirle una ventana propia sería un clic de más para algo
 * que se resuelve ahí mismo.
 */
export function SettingsMenu({ onClose, onOpenChime, onOpenSnippets, onOpenLinks }) {
  const { t } = useT()
  const opciones = [
    {
      key: 'chime',
      icon: <BellIcon />,
      label: t('chime.title'),
      hint: t('settings.chime_hint'),
      onClick: onOpenChime,
    },
    {
      key: 'snippets',
      icon: <BoltIcon />,
      label: t('snippets.title'),
      hint: t('settings.snippets_hint'),
      onClick: onOpenSnippets,
    },
    {
      key: 'links',
      icon: <LinkIcon />,
      label: t('links.title'),
      hint: t('settings.links_hint'),
      onClick: onOpenLinks,
    },
  ]
  return (
    <Modal title={t('settings.title')} onClose={onClose}>
      <ul className="space-y-2">
        {opciones.map((o) => (
          <li key={o.key}>
            <button
              type="button"
              onClick={o.onClick}
              className="flex w-full items-center gap-3 rounded border border-panel-border px-3 py-3 text-left transition hover:border-panel-accent hover:bg-panel-bg"
            >
              <span className="shrink-0 text-panel-muted">{o.icon}</span>
              <span className="min-w-0">
                <span className="block text-xs font-medium text-gray-100">
                  {o.label}
                </span>
                <span className="block text-xs text-panel-muted">{o.hint}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex items-center justify-between gap-3 rounded border border-panel-border px-3 py-3">
        <span className="min-w-0">
          <span className="block text-xs font-medium text-gray-100">
            {t('lang.label')}
          </span>
          <span className="block text-xs text-panel-muted">
            {t('settings.lang_hint')}
          </span>
        </span>
        <LanguagePicker />
      </div>
    </Modal>
  )
}
