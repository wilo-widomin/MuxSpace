import React, { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api.js'
import { UNASSIGNED } from '../spaces.js'
import { formatDuration } from '../worklog.js'
import { useT } from '../i18n/index.jsx'

// Vista de tiempos: cuántas horas MÍAS lleva cada proyecto.
//
// Se consulta al cerrar un proyecto, no a diario, así que está hecha para
// responder rápido a dos preguntas y a ninguna más: cuánto pesa cada espacio
// en un rango, y cómo se reparte por días.
//
// Colores: dos series (con un agente delante / resto) tomadas de la paleta
// categórica de la guía, en sus pasos para fondo oscuro. Están validadas
// contra el fondo del panel (#0d1117): separación en protanopia ΔE 26.8 y
// contraste ≥3:1. No se eligieron a ojo, y cambiarlas obliga a revalidar.
const SERIE_AGENTE = '#3987e5'
const SERIE_RESTO = '#d95926'

const RANGOS = [
  { id: '7d', dias: 7 },
  { id: '30d', dias: 30 },
  { id: '90d', dias: 90 },
  { id: 'all', dias: null },
]

// Inicio del día local de hace `dias` días. Se usa el día LOCAL, igual que la
// agrupación del servidor: si no, el rango cortaría a media jornada.
function desdeHace(dias) {
  if (dias === null) return undefined
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - (dias - 1))
  return d.getTime()
}

export default function Dashboard({ spaces = [] }) {
  const { t, tError } = useT()
  const [rango, setRango] = useState('30d')
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(null)
  const [verTabla, setVerTabla] = useState(false)

  const cargar = useCallback(async () => {
    const elegido = RANGOS.find((r) => r.id === rango)
    try {
      setError(null)
      setDatos(await api.workSummary({ desde: desdeHace(elegido.dias) }))
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0))
    }
  }, [rango])

  useEffect(() => {
    cargar()
  }, [cargar])

  const titulo = useCallback(
    (id) => {
      if (id === UNASSIGNED) return t('spaces.unassigned')
      return spaces.find((s) => s.id === id)?.title || id
    },
    [spaces, t],
  )

  const porEspacio = datos?.by_space || []
  const porDia = datos?.by_day || []
  const maxEspacio = Math.max(1, ...porEspacio.map((e) => e.seconds))
  const maxDia = Math.max(1, ...porDia.map((d) => d.seconds))

  // Media por día CON trabajo, no por día del calendario: dividir entre los
  // 30 días del rango cuando se trabajó 8 daría un número que no significa
  // nada.
  const diasConTrabajo = porDia.length
  const media = diasConTrabajo
    ? Math.round((datos?.total_seconds || 0) / diasConTrabajo)
    : 0

  return (
    <div className="h-full w-full overflow-y-auto bg-panel-bg text-gray-100">
      <div className="mx-auto max-w-4xl px-6 py-6">
        <header className="mb-6 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">{t('dashboard.title')}</h1>
          <a
            href="/"
            className="text-xs text-panel-muted underline-offset-2 hover:text-gray-100 hover:underline"
          >
            {t('dashboard.back')}
          </a>
          <div className="ml-auto flex items-center gap-1">
            {RANGOS.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setRango(r.id)}
                aria-pressed={rango === r.id}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  rango === r.id
                    ? 'border-panel-accent bg-panel-accent/20 text-gray-100'
                    : 'border-panel-border text-panel-muted hover:text-gray-100'
                }`}
              >
                {t(`dashboard.range_${r.id}`)}
              </button>
            ))}
          </div>
        </header>

        {error && <p className="text-sm text-red-400">{tError(error)}</p>}
        {!error && !datos && (
          <p className="text-sm text-panel-muted">{t('dashboard.loading')}</p>
        )}

        {datos && (
          <>
            {/* Tres cifras, sin gráfico: son totales, no comparaciones. */}
            <section className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Cifra
                etiqueta={t('dashboard.total')}
                valor={formatDuration(datos.total_seconds)}
              />
              <Cifra
                etiqueta={t('dashboard.days_worked')}
                valor={String(diasConTrabajo)}
              />
              <Cifra
                etiqueta={t('dashboard.avg_per_day')}
                valor={formatDuration(media)}
              />
            </section>

            <section className="mb-8">
              <h2 className="mb-1 text-sm font-medium">{t('dashboard.by_space')}</h2>
              <Leyenda t={t} />
              {porEspacio.length === 0 && (
                <p className="text-sm text-panel-muted">{t('dashboard.empty')}</p>
              )}
              <table className="w-full border-collapse text-sm">
                <tbody>
                  {porEspacio.map((e) => (
                    <tr key={e.space} className="border-b border-panel-border/50">
                      <th
                        scope="row"
                        className="w-40 truncate py-2 pr-3 text-left font-normal text-gray-200"
                        title={titulo(e.space)}
                      >
                        {titulo(e.space)}
                      </th>
                      <td className="py-2">
                        <BarraEspacio
                          total={e.seconds}
                          agente={e.claude_seconds}
                          max={maxEspacio}
                          t={t}
                        />
                      </td>
                      {/* El valor va escrito al lado de la barra: la longitud
                          compara, el número informa. */}
                      <td className="w-28 py-2 pl-3 text-right tabular-nums text-gray-200">
                        {formatDuration(e.seconds)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section>
              <div className="mb-2 flex items-center gap-3">
                <h2 className="text-sm font-medium">{t('dashboard.by_day')}</h2>
                <button
                  type="button"
                  onClick={() => setVerTabla((v) => !v)}
                  className="text-xs text-panel-muted underline-offset-2 hover:text-gray-100 hover:underline"
                >
                  {verTabla ? t('dashboard.as_chart') : t('dashboard.as_table')}
                </button>
              </div>
              {porDia.length === 0 ? (
                <p className="text-sm text-panel-muted">{t('dashboard.empty')}</p>
              ) : verTabla ? (
                <TablaDias dias={porDia} t={t} />
              ) : (
                <GraficoDias dias={porDia} max={maxDia} />
              )}
            </section>

            {datos.since && (
              <p className="mt-6 text-xs text-panel-muted">
                {t('dashboard.since', {
                  date: new Date(datos.since * 1000).toLocaleDateString(),
                })}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Cifra({ etiqueta, valor }) {
  return (
    <div className="rounded border border-panel-border bg-panel-surface px-4 py-3">
      <div className="text-xs text-panel-muted">{etiqueta}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{valor}</div>
    </div>
  )
}

// Dos series: la identidad nunca depende solo del color (hay leyenda, y el
// título de cada tramo lleva su nombre).
function Leyenda({ t }) {
  return (
    <div className="mb-3 flex items-center gap-4 text-xs text-panel-muted">
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-sm"
          style={{ background: SERIE_AGENTE }}
        />
        {t('dashboard.series_agent')}
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-2.5 w-2.5 rounded-sm"
          style={{ background: SERIE_RESTO }}
        />
        {t('dashboard.series_other')}
      </span>
    </div>
  )
}

// Barra apilada: la parte con un agente delante y el resto. El hueco de 2 px
// entre tramos es lo que evita que dos colores contiguos se lean como uno.
function BarraEspacio({ total, agente, max, t }) {
  const ancho = (total / max) * 100
  const proporcionAgente = total ? agente / total : 0
  return (
    <div className="h-3 w-full">
      <div className="flex h-full" style={{ width: `${ancho}%` }}>
        <div
          className="h-full rounded-l-sm"
          style={{
            width: `${proporcionAgente * 100}%`,
            background: SERIE_AGENTE,
            marginRight: proporcionAgente > 0 && proporcionAgente < 1 ? 2 : 0,
          }}
          title={`${t('dashboard.series_agent')}: ${formatDuration(agente)}`}
        />
        <div
          className="h-full flex-1 rounded-r-sm"
          style={{ background: SERIE_RESTO }}
          title={`${t('dashboard.series_other')}: ${formatDuration(total - agente)}`}
        />
      </div>
    </div>
  )
}

// Una serie por día: sin leyenda (el título ya la nombra) y sin número encima
// de cada barra; el valor aparece al pasar por encima y en la vista de tabla.
function GraficoDias({ dias, max }) {
  return (
    <div className="flex h-40 items-end gap-1 border-b border-panel-border pb-0">
      {dias.map((d) => (
        <div
          key={d.day}
          className="group relative flex-1"
          style={{ minWidth: 4 }}
          title={`${d.day} · ${formatDuration(d.seconds)}`}
        >
          <div
            className="w-full rounded-t-sm transition-opacity group-hover:opacity-80"
            style={{
              height: `${Math.max(2, (d.seconds / max) * 150)}px`,
              background: SERIE_AGENTE,
            }}
          />
        </div>
      ))}
    </div>
  )
}

function TablaDias({ dias, t }) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-xs text-panel-muted">
          <th scope="col" className="py-1 text-left font-normal">
            {t('dashboard.day')}
          </th>
          <th scope="col" className="py-1 text-right font-normal">
            {t('dashboard.time')}
          </th>
        </tr>
      </thead>
      <tbody>
        {dias.map((d) => (
          <tr key={d.day} className="border-b border-panel-border/50">
            <td className="py-1 text-gray-200">{d.day}</td>
            <td className="py-1 text-right tabular-nums text-gray-200">
              {formatDuration(d.seconds)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
