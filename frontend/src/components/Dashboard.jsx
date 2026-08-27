import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api.js'
import { UNASSIGNED } from '../spaces.js'
import {
  formatDate,
  formatDuration,
  formatDurationExact,
  formatTime,
} from '../worklog.js'
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
  // «Hoy» es un rango de un día: desde las 00:00 locales de hoy.
  { id: 'today', dias: 1 },
  { id: '7d', dias: 7 },
  { id: '30d', dias: 30 },
  { id: '90d', dias: 90 },
  { id: 'all', dias: null },
]

// Topes del puente de continuidad que ofrece el selector, en minutos. 0 lo
// apaga (solo tiempo medido). Salen de la distribución real de huecos: por
// debajo de 10 min son saltos de ventana dentro de una misma sesión de
// trabajo y por encima de 30 ya son ausencias, así que los valores
// interesantes están todos aquí.
const PUENTES = [0, 3, 5, 10, 15, 20, 30]

// Dónde se recuerda el tope elegido. Es una preferencia de LECTURA —no cambia
// ni un dato— así que vive en el navegador y no en el servidor: probar valores
// desde una pestaña no puede alterar lo que ve el resto.
const PUENTE_GUARDADO = 'muxspace.dashboard.bridge'

function leerPuenteGuardado() {
  try {
    const valor = Number(window.localStorage.getItem(PUENTE_GUARDADO))
    return PUENTES.includes(valor) ? valor : null
  } catch {
    // Sin almacenamiento (modo privado, permisos): manda el servidor.
    return null
  }
}

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
  const [tramos, setTramos] = useState([])
  const [error, setError] = useState(null)
  const [verTabla, setVerTabla] = useState(false)
  // Fechas a mano: mandan sobre el rango de botones en cuanto se rellena una.
  // Se guardan como 'YYYY-MM-DD' (lo que da un <input type="date">).
  const [desdeFecha, setDesdeFecha] = useState('')
  const [hastaFecha, setHastaFecha] = useState('')
  const [espacioFiltro, setEspacioFiltro] = useState('')
  // Modo de cálculo. Se recuerda en el navegador porque es una preferencia de
  // lectura, no un filtro: quien mira sus horas quiere verlas siempre con el
  // mismo criterio, y volver al de por defecto en cada visita haría que dos
  // consultas del mismo día dieran números distintos sin motivo aparente.
  const [modo, setModo] = useState(() => {
    try {
      return localStorage.getItem('muxspace.worklog.modo') || ''
    } catch {
      return ''
    }
  })
  const [pausasDelPeriodo, setPausasDelPeriodo] = useState([])

  useEffect(() => {
    try {
      if (modo) localStorage.setItem('muxspace.worklog.modo', modo)
      else localStorage.removeItem('muxspace.worklog.modo')
    } catch {
      // Sin almacenamiento (ventana privada) se pierde la preferencia y no
      // pasa nada más: el modo del servidor sigue siendo el que manda.
    }
  }, [modo])
  // Tope del puente. `null` = todavía no se ha elegido nada aquí: manda el
  // valor por defecto del servidor, y el selector se pone al recibirlo. Así
  // el desplegable nunca enseña un número distinto del que produjo el total.
  const [puente, setPuente] = useState(leerPuenteGuardado)

  // El rango efectivo en milisegundos. Las fechas escritas se interpretan en
  // hora LOCAL —«desde el 1» es desde las 00:00 de tu día, no de UTC— y el
  // «hasta» incluye el día entero: si no, filtrar «hasta hoy» dejaría fuera
  // todo lo de hoy.
  const { desde, hasta } = useMemo(() => {
    if (desdeFecha || hastaFecha) {
      const ini = desdeFecha ? new Date(`${desdeFecha}T00:00:00`).getTime() : undefined
      const fin = hastaFecha ? new Date(`${hastaFecha}T23:59:59`).getTime() : undefined
      return { desde: ini, hasta: fin }
    }
    const elegido = RANGOS.find((r) => r.id === rango)
    // El «hasta» se congela al cargar aunque no se haya elegido ninguno. Sin
    // eso, el resumen y la lista de tramos son dos consultas con dos cortes
    // distintos: un latido que cae entre ambas aparece en una y no en la
    // otra, y los totales se separan justo en 30 segundos. Se ve como un
    // error de cuentas y no lo es.
    return { desde: desdeHace(elegido.dias), hasta: Date.now() }
  }, [rango, desdeFecha, hastaFecha])

  const cargar = useCallback(async () => {
    try {
      setError(null)
      // Las tres consultas comparten modo y tope: con criterios distintos, la
      // lista de abajo no sumaría el total de arriba y parecería un error de
      // cuentas que no lo es.
      const [resumen, bloques, pausas] = await Promise.all([
        api.workSummary({
          desde,
          hasta,
          bridge: puente,
          space: espacioFiltro || undefined,
          modo,
        }),
        api.workBlocks({
          desde,
          hasta,
          space: espacioFiltro || undefined,
          bridge: puente,
          modo,
        }),
        api.workPauses({ desde, hasta }),
      ])
      setDatos(resumen)
      setTramos(bloques)
      setPausasDelPeriodo(pausas.pauses || [])
      // Sin modo elegido a mano manda el del servidor, y hay que saberlo para
      // poder explicar en pantalla qué se está contando.
      if (!modo && pausas.mode) setModo(pausas.mode)
      // El servidor dice con qué tope calculó. Se adopta solo la primera vez
      // (cuando aquí no había elegido nada): a partir de ahí manda el
      // selector, y adoptarlo siempre lo dejaría clavado en el default.
      if (puente === null) setPuente(resumen.bridge_minutes ?? 0)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0))
    }
  }, [desde, hasta, espacioFiltro, puente, modo])

  useEffect(() => {
    cargar()
  }, [cargar])

  const quitarPausa = useCallback(
    async (inicio) => {
      try {
        await api.deletePause(inicio * 1000)
        await cargar()
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0))
      }
    },
    [cargar],
  )

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
                onClick={() => {
                  // Elegir un rango de botones descarta las fechas escritas:
                  // dos filtros de fecha a la vez, uno de ellos invisible,
                  // es la forma más fácil de leer mal un total.
                  setDesdeFecha('')
                  setHastaFecha('')
                  setRango(r.id)
                }}
                aria-pressed={!desdeFecha && !hastaFecha && rango === r.id}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  !desdeFecha && !hastaFecha && rango === r.id
                    ? 'border-panel-accent bg-panel-accent/20 text-gray-100'
                    : 'border-panel-border text-panel-muted hover:text-gray-100'
                }`}
              >
                {t(`dashboard.range_${r.id}`)}
              </button>
            ))}
          </div>
        </header>

        <div className="mb-6 flex flex-wrap items-center gap-2 text-xs text-panel-muted">
          <label className="flex items-center gap-1">
            {t('dashboard.from')}
            <input
              type="date"
              value={desdeFecha}
              onChange={(e) => setDesdeFecha(e.target.value)}
              className="rounded border border-panel-border bg-panel-surface px-2 py-1 text-gray-100 outline-none"
            />
          </label>
          <label className="flex items-center gap-1">
            {t('dashboard.to')}
            <input
              type="date"
              value={hastaFecha}
              onChange={(e) => setHastaFecha(e.target.value)}
              className="rounded border border-panel-border bg-panel-surface px-2 py-1 text-gray-100 outline-none"
            />
          </label>
          <label className="flex items-center gap-1">
            {t('dashboard.space')}
            <select
              value={espacioFiltro}
              onChange={(e) => setEspacioFiltro(e.target.value)}
              className="rounded border border-panel-border bg-panel-surface px-2 py-1 text-gray-100 outline-none"
            >
              <option value="">{t('dashboard.all_spaces')}</option>
              <option value={UNASSIGNED}>{t('spaces.unassigned')}</option>
              {spaces.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1" title={t('dashboard.bridge_hint')}>
            {t('dashboard.bridge')}
            <select
              value={puente ?? ''}
              onChange={(e) => {
                const valor = Number(e.target.value)
                setPuente(valor)
                try {
                  window.localStorage.setItem(PUENTE_GUARDADO, String(valor))
                } catch {
                  // Sin almacenamiento el tope vale para esta pestaña y ya.
                }
              }}
              className="rounded border border-panel-border bg-panel-surface px-2 py-1 text-gray-100 outline-none"
            >
              {PUENTES.map((min) => (
                <option key={min} value={min}>
                  {min === 0 ? t('dashboard.bridge_off') : `${min} min`}
                </option>
              ))}
            </select>
          </label>
          {/* El modo es lo primero que hay que poder ver y cambiar: dos
              números distintos del mismo día no son un error si se sabe cuál
              de los dos criterios los produjo. */}
          <label className="flex items-center gap-1">
            {t('dashboard.mode')}
            <select
              value={modo}
              onChange={(e) => setModo(e.target.value)}
              className="rounded border border-panel-border bg-panel-surface px-2 py-1 text-gray-100 outline-none"
            >
              <option value="workday">{t('dashboard.mode_workday')}</option>
              <option value="measured">{t('dashboard.mode_measured')}</option>
            </select>
          </label>
          {(desdeFecha || hastaFecha || espacioFiltro) && (
            <button
              type="button"
              onClick={() => {
                setDesdeFecha('')
                setHastaFecha('')
                setEspacioFiltro('')
              }}
              className="underline-offset-2 hover:text-gray-100 hover:underline"
            >
              {t('dashboard.clear_filters')}
            </button>
          )}
        </div>

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

            <p className="-mt-6 mb-8 text-xs text-panel-muted">
              {t(`dashboard.mode_hint_${modo || 'workday'}`)}
            </p>

            {/* El tiempo declarado a mano se enseña aparte del medido. Si un
                día el total no cuadra con lo que uno recuerda, lo primero que
                hay que poder mirar es qué parte se declaró. */}
            {(datos.manual_seconds > 0 || datos.bridge_seconds > 0) && (
              <div className="-mt-6 mb-8 space-y-1 text-xs text-panel-muted">
                {datos.manual_seconds > 0 && (
                  <p>
                    {t('dashboard.declared_note', {
                      time: formatDuration(datos.manual_seconds),
                    })}
                  </p>
                )}
                {/* Y lo mismo con el tiempo que puso el puente: es deducción,
                    no medida, y va con el tope que la produjo. Sin el tope, el
                    número no se puede interpretar ni discutir. */}
                {datos.bridge_seconds > 0 && (
                  <p>
                    {t('dashboard.bridge_note', {
                      time: formatDuration(datos.bridge_seconds),
                      min: String(datos.bridge_minutes),
                    })}
                  </p>
                )}
              </div>
            )}

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

            {/* Las pausas, solo en el modo que las usa. Se pueden quitar: una
                marcada de más resta trabajo real, y el usuario tiene que poder
                deshacerla sin tocar la base a mano. */}
            {modo === 'workday' && (
              <section className="mt-8">
                <h2 className="mb-2 text-sm font-medium">{t('dashboard.pauses')}</h2>
                {pausasDelPeriodo.length === 0 ? (
                  <p className="text-sm text-panel-muted">{t('dashboard.no_pauses')}</p>
                ) : (
                  <ul className="text-sm">
                    {pausasDelPeriodo.map((pausa) => (
                      <li
                        key={pausa.start}
                        className="flex items-center gap-3 border-b border-panel-border/50 py-1"
                      >
                        <span className="tabular-nums text-gray-200">
                          {formatDate(pausa.start)} {formatTime(pausa.start)}
                          {' → '}
                          {pausa.end ? formatTime(pausa.end) : '…'}
                        </span>
                        <span className="text-xs text-panel-muted">
                          {pausa.end
                            ? formatDuration(pausa.end - pausa.start)
                            : t('clock.resume')}
                        </span>
                        <button
                          type="button"
                          onClick={() => quitarPausa(pausa.start)}
                          className="ml-auto text-xs text-panel-muted underline-offset-2 hover:text-gray-100 hover:underline"
                        >
                          {t('dashboard.pause_delete')}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            <section className="mt-8">
              <div className="mb-1 flex flex-wrap items-baseline gap-2">
                <h2 className="text-sm font-medium">{t('dashboard.blocks')}</h2>
                {/* El total de LO LISTADO, no el de la página: con el filtro de
                    espacio puesto, los dos números no coinciden y el de aquí es
                    el que responde a "cuánto suma esto que estoy viendo". */}
                <span className="text-xs text-panel-muted">
                  {t('dashboard.blocks_total', {
                    count: tramos.length,
                    time: formatDurationExact(
                      tramos.reduce((suma, b) => suma + b.seconds, 0),
                    ),
                  })}
                </span>
              </div>
              <p className="mb-3 text-xs text-panel-muted">
                {t('dashboard.blocks_hint')}
              </p>
              {tramos.length === 0 ? (
                <p className="text-sm text-panel-muted">{t('dashboard.empty')}</p>
              ) : (
                <TablaTramos tramos={tramos} titulo={titulo} t={t} />
              )}
            </section>

            {datos.since && (
              <p className="mt-6 text-xs text-panel-muted">
                {t('dashboard.since', { date: formatDate(datos.since) })}
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

// Una serie por día: una barra por cada día del calendario con tiempo
// registrado, y su altura es el total de ese día. Sin leyenda (el título ya
// la nombra) y sin número encima de cada barra, pero SÍ con la fecha debajo y
// el máximo como referencia: una barra suelta sin escala ni etiqueta no dice
// nada, y este gráfico empieza siempre con un solo día.
function GraficoDias({ dias, max }) {
  // Con muchos días, las fechas se pisarían: se etiquetan salteadas.
  const cadaCuantas = Math.ceil(dias.length / 12)
  return (
    <div>
      <div className="mb-1 text-xs text-panel-muted">
        {formatDuration(max)} {'\u2191'}
      </div>
      <div className="flex h-40 items-end gap-1 border-b border-panel-border">
        {dias.map((d) => (
          <div
            key={d.day}
            className="group relative flex-1"
            // Con pocos días, sin tope cada barra ocuparía media pantalla y el
            // gráfico dejaría de leerse como un gráfico.
            style={{ minWidth: 4, maxWidth: 48 }}
            title={`${formatDate(d.day)} · ${formatDuration(d.seconds)}`}
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
      <div className="flex gap-1">
        {dias.map((d, i) => (
          <div
            key={d.day}
            className="flex-1 pt-1 text-center text-[10px] text-panel-muted"
            style={{ minWidth: 4, maxWidth: 48 }}
          >
            {i % cadaCuantas === 0 ? formatDate(d.day).slice(0, 5) : ''}
          </div>
        ))}
      </div>
    </div>
  )
}

function TablaTramos({ tramos, titulo, t }) {
  // Fechas siempre en dd/mm/aaaa y horas en 24 h CON segundos: las ranuras
  // duran 30 s, y sin los segundos el fin de un tramo y el principio del
  // siguiente se pintan iguales y parecen solaparse (no lo hacen: una ranura
  // solo puede pertenecer a un espacio).
  const hora = (epoch) => formatTime(epoch, { segundos: true })
  const fecha = formatDate

  // Acumulado CRONOLÓGICO: cuánto se llevaba sumado hasta el final de cada
  // tramo. Se calcula en orden ascendente y se pinta al revés (la lista va de
  // lo más reciente a lo más antiguo), así la primera fila coincide con el
  // total de la tarjeta de arriba y hacia abajo se ve cómo fue creciendo.
  // Acumular en el orden de pintado daría "lo que queda por sumar", que no es
  // una cifra que nadie busque.
  let suma = 0
  const filas = tramos
    .map((b) => {
      suma += b.seconds
      return { ...b, acumulado: suma }
    })
    .reverse()

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-xs text-panel-muted">
          <th scope="col" className="py-1 text-left font-normal">
            {t('dashboard.space')}
          </th>
          <th scope="col" className="py-1 text-left font-normal">
            {t('dashboard.start')}
          </th>
          <th scope="col" className="py-1 text-left font-normal">
            {t('dashboard.end')}
          </th>
          <th scope="col" className="py-1 pr-3 text-right font-normal">
            {t('dashboard.time')}
          </th>
          <th
            scope="col"
            className="py-1 pr-3 text-right font-normal"
            title={t('dashboard.cumulative_hint')}
          >
            {t('dashboard.cumulative')}
          </th>
          <th scope="col" className="py-1 text-left font-normal">
            {t('dashboard.program')}
          </th>
        </tr>
      </thead>
      <tbody>
        {filas.map((b) => {
          const mismoDia = fecha(b.start) === fecha(b.end)
          return (
            <tr
              key={`${b.space}-${b.start}`}
              className="border-b border-panel-border/50"
            >
              <td className="py-1 pr-3 text-gray-200">
                {titulo(b.space)}
                {b.manual_seconds > 0 && (
                  <span
                    className="ml-2 rounded-full border border-amber-400/60 px-1.5 py-0.5 text-[10px] text-amber-400"
                    title={t('dashboard.declared_hint')}
                  >
                    {t('dashboard.declared')}
                  </span>
                )}
                {b.bridge_seconds > 0 && (
                  <span
                    className="ml-2 rounded-full border border-panel-border px-1.5 py-0.5 text-[10px] text-panel-muted"
                    title={t('dashboard.inferred_hint', {
                      time: formatDurationExact(b.bridge_seconds),
                    })}
                  >
                    {t('dashboard.inferred')}
                  </span>
                )}
              </td>
              <td className="py-1 pr-3 tabular-nums text-gray-200">
                {fecha(b.start)} {hora(b.start)}
              </td>
              <td className="py-1 pr-3 tabular-nums text-gray-200">
                {mismoDia ? hora(b.end) : `${fecha(b.end)} ${hora(b.end)}`}
              </td>
              <td className="py-1 pr-3 text-right tabular-nums text-gray-200">
                {formatDurationExact(b.seconds)}
              </td>
              {/* Apagado respecto a la duración del tramo: es contexto, no el
                  dato de la fila. Si los dos números pesan igual, la columna
                  que se lee mal es la que de verdad importa. */}
              <td className="py-1 pr-3 text-right tabular-nums text-panel-muted">
                {formatDuration(b.acumulado)}
              </td>
              {/* El programa, no la sesión: cuando cada sesión se llama
                  como su espacio, el nombre repetía la primera columna. Los
                  nombres siguen ahí, en el tooltip. */}
              <td
                className="max-w-[14rem] truncate py-1 text-panel-muted"
                title={
                  b.sessions.length
                    ? `${t('dashboard.sessions')}: ${b.sessions.join(', ')}`
                    : undefined
                }
              >
                {b.commands.join(', ')}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
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
            <td className="py-1 text-gray-200">{formatDate(d.day)}</td>
            <td className="py-1 text-right tabular-nums text-gray-200">
              {formatDuration(d.seconds)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
