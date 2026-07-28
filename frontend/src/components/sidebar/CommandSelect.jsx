import { useT } from '../../i18n/index.jsx'

// <select> para elegir un comando de la biblioteca al componer un proyecto.
// El valor almacenado es la propia línea de comando (no el id), de modo que
// el proyecto queda como una secuencia autónoma de comandos.
export function CommandSelect({ value, onChange, commands }) {
  const { t } = useT()
  const exists = commands.some((c) => c.command === value)
  return (
    <select
      value={exists ? value : ''}
      onChange={(e) => onChange(e.target.value)}
      className="min-w-0 flex-1 rounded border border-panel-border bg-panel-bg px-2 py-1 text-xs outline-none focus:border-panel-accent"
    >
      <option value="">{t('form.pick_command')}</option>
      {commands.map((c) => (
        <option key={c.id} value={c.command}>
          {c.label}
        </option>
      ))}
      {!exists && value && (
        // El comando guardado ya no está en la biblioteca: lo mostramos
        // igual para no perderlo al editar.
        <option value={value}>{value}</option>
      )}
    </select>
  )
}
