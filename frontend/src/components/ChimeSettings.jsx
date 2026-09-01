import { useEffect, useRef, useState } from 'react'

import { api } from '../api.js'
import { useT } from '../i18n/index.jsx'
import {
  configure,
  DEFAULT_CONFIG,
  PRESETS,
  previewChime,
  recipeOf,
} from '../lib/chime.js'
import { Modal } from './sidebar/Modal.jsx'

// Cuántas notas admite el editor. Tiene que coincidir con `MAX_NOTES` de
// `backend/chime_store.py`: aquí para no dejar añadir de más, allí porque el
// navegador no es quien decide qué se guarda.
const MAX_NOTES = 16

// Nota nueva: se encadena a la última para que añadirla suene a continuación
// y no encima. Empezar con todo a cero obligaría a teclear el retardo antes
// de poder oír nada, que es justo lo que un editor así tiene que ahorrar.
function nextNote(notes) {
  const last = notes[notes.length - 1]
  return {
    freq: last ? Math.round(last.freq * 1.25) : 880,
    delay: last ? Number((last.delay + 0.1).toFixed(2)) : 0,
    duration: 0.4,
  }
}

function clamp(value, lo, hi, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(hi, Math.max(lo, n))
}

/** Botón de oír un ajuste sin guardarlo. */
function PlayButton({ onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="rounded p-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M8 5v14l11-7z" />
      </svg>
    </button>
  )
}

/**
 * Ajustes de la campanilla del aviso: qué suena, cuánto y si suena.
 *
 * Todo lo que se toca aquí se oye al momento con el botón de probar, y nada
 * se guarda hasta darle a guardar: una campanilla se elige oyéndola, y
 * persistir cada clic dejaría al resto de dispositivos con lo que este
 * estaba tanteando.
 */
export function ChimeSettings({ onClose, onSaved }) {
  const { t, tError } = useT()
  const [cfg, setCfg] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const fileInput = useRef(null)

  useEffect(() => {
    let vivo = true
    api
      .getChime()
      .then((data) => vivo && setCfg(data))
      // Sin ajuste del servidor se edita sobre el de fábrica: es preferible
      // a un diálogo vacío que no deja hacer nada.
      .catch(() => vivo && setCfg({ ...DEFAULT_CONFIG }))
    return () => {
      vivo = false
    }
  }, [])

  if (!cfg) return null

  const patch = (cambio) => setCfg((prev) => ({ ...prev, ...cambio }))

  // Lo que devuelve el servidor manda, y pasa a sonar YA: guardar una
  // campanilla y que el siguiente aviso siga sonando como el anterior hasta
  // recargar la página sería la peor forma de estrenarla.
  const aplicar = (guardado) => {
    setCfg(guardado)
    configure(guardado)
    onSaved?.(guardado)
  }

  // Pasar a "el mío" copiando las notas del preset que sonaba: se empieza a
  // trastear desde algo que ya suena bien, no desde una lista vacía.
  const startCustom = () => {
    if (cfg.mode === 'custom') return
    const receta = recipeOf(cfg)
    patch({
      mode: 'custom',
      timbre: receta.timbre,
      notes: receta.notes.map((n) => ({ ...n })),
    })
  }

  const setNote = (i, campo, valor) => {
    const notes = cfg.notes.map((n, j) => (i === j ? { ...n, [campo]: valor } : n))
    patch({ notes })
  }

  async function guardar() {
    setBusy(true)
    setError(null)
    try {
      const guardado = await api.saveChime(cfg)
      aplicar(guardado)
      onClose()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function subirAudio(file) {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const guardado = await api.uploadChimeAudio(file)
      aplicar(guardado)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function quitarAudio() {
    setBusy(true)
    setError(null)
    try {
      const guardado = await api.deleteChimeAudio()
      aplicar(guardado)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const fila = 'flex items-center gap-2 rounded px-2 py-1.5 hover:bg-panel-bg'

  return (
    <Modal title={t('chime.title')} onClose={onClose} panelClassName="max-w-lg">
      {/* Silenciar es un ajuste aparte del sonido elegido: al volver a
          activarlo suena lo que ya estaba, no hay que elegirlo otra vez. */}
      <label className="mb-3 flex items-center gap-2 text-sm text-gray-200">
        <input
          type="checkbox"
          checked={!cfg.muted}
          onChange={(e) => patch({ muted: !e.target.checked })}
        />
        {t('chime.enabled')}
      </label>

      <fieldset disabled={cfg.muted} className={cfg.muted ? 'opacity-50' : ''}>
        <div className="mb-3">
          {Object.keys(PRESETS).map((id) => (
            <div key={id} className={fila}>
              <label className="flex flex-1 cursor-pointer items-center gap-2 text-sm text-gray-200">
                <input
                  type="radio"
                  name="chime-sound"
                  checked={cfg.mode === 'preset' && cfg.preset === id}
                  onChange={() => patch({ mode: 'preset', preset: id })}
                />
                {t(`chime.preset.${id}`)}
              </label>
              <PlayButton
                label={t('chime.play')}
                onClick={() =>
                  previewChime({ ...cfg, mode: 'preset', preset: id, muted: false })
                }
              />
            </div>
          ))}

          {/* El mío: notas escritas a mano */}
          <div className={fila}>
            <label className="flex flex-1 cursor-pointer items-center gap-2 text-sm text-gray-200">
              <input
                type="radio"
                name="chime-sound"
                checked={cfg.mode === 'custom'}
                onChange={startCustom}
              />
              {t('chime.custom')}
            </label>
            <PlayButton
              label={t('chime.play')}
              onClick={() => previewChime({ ...cfg, muted: false })}
            />
          </div>

          {/* Mi archivo */}
          <div className={fila}>
            <label className="flex flex-1 cursor-pointer items-center gap-2 text-sm text-gray-200">
              <input
                type="radio"
                name="chime-sound"
                disabled={!cfg.file}
                checked={cfg.mode === 'file'}
                onChange={() => patch({ mode: 'file' })}
              />
              <span className={cfg.file ? '' : 'text-panel-muted'}>
                {cfg.file
                  ? t('chime.fileNamed', { name: cfg.file })
                  : t('chime.noFile')}
              </span>
            </label>
            {cfg.file && (
              <PlayButton
                label={t('chime.play')}
                onClick={() => previewChime({ ...cfg, mode: 'file', muted: false })}
              />
            )}
          </div>
        </div>

        {cfg.mode === 'custom' && (
          <div className="mb-3 rounded border border-panel-border p-2">
            <table className="w-full text-xs text-gray-300">
              <thead className="text-panel-muted">
                <tr>
                  <th className="pb-1 text-left font-normal">{t('chime.freq')}</th>
                  <th className="pb-1 text-left font-normal">{t('chime.delay')}</th>
                  <th className="pb-1 text-left font-normal">{t('chime.duration')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {cfg.notes.map((nota, i) => (
                  <tr key={i}>
                    {[
                      ['freq', 20, 12000, 1],
                      ['delay', 0, 5, 0.01],
                      ['duration', 0.02, 5, 0.01],
                    ].map(([campo, lo, hi, step]) => (
                      <td key={campo} className="pr-2 pb-1">
                        <input
                          type="number"
                          min={lo}
                          max={hi}
                          step={step}
                          value={nota[campo]}
                          aria-label={t(`chime.${campo}`)}
                          onChange={(e) =>
                            setNote(
                              i,
                              campo,
                              clamp(e.target.value, lo, hi, nota[campo]),
                            )
                          }
                          className="w-20 rounded border border-panel-border bg-panel-bg px-1.5 py-1 outline-none focus:border-panel-accent"
                        />
                      </td>
                    ))}
                    <td className="pb-1">
                      {/* La última nota no se puede quitar: sin ninguna, el
                          aviso sería mudo y parecería estropeado. */}
                      <button
                        type="button"
                        disabled={cfg.notes.length <= 1}
                        onClick={() =>
                          patch({ notes: cfg.notes.filter((_, j) => j !== i) })
                        }
                        title={t('chime.removeNote')}
                        aria-label={t('chime.removeNote')}
                        className="rounded px-1.5 py-1 text-panel-muted transition hover:bg-panel-bg hover:text-gray-100 disabled:opacity-30"
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-2 flex items-center gap-3">
              <button
                type="button"
                disabled={cfg.notes.length >= MAX_NOTES}
                onClick={() => patch({ notes: [...cfg.notes, nextNote(cfg.notes)] })}
                className="rounded border border-panel-border px-2 py-1 text-xs text-gray-200 transition hover:bg-panel-bg disabled:opacity-40"
              >
                {t('chime.addNote')}
              </button>
              <label className="flex items-center gap-1.5 text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={cfg.timbre === 'bell'}
                  onChange={(e) =>
                    patch({ timbre: e.target.checked ? 'bell' : 'sine' })
                  }
                />
                {t('chime.bellTimbre')}
              </label>
            </div>
          </div>
        )}

        <label className="mb-3 block text-sm text-gray-200">
          {t('chime.volume')}
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={cfg.volume}
            onChange={(e) => patch({ volume: Number(e.target.value) })}
            onMouseUp={() => previewChime({ ...cfg, muted: false })}
            className="mt-1 w-full"
          />
        </label>

        <div className="mb-3">
          <input
            ref={fileInput}
            type="file"
            accept="audio/mpeg,audio/wav,audio/ogg,audio/webm,.mp3,.wav,.ogg"
            onChange={(e) => subirAudio(e.target.files?.[0])}
            className="w-full text-xs text-panel-muted file:mr-2 file:rounded file:border file:border-panel-border file:bg-panel-bg file:px-2 file:py-1 file:text-gray-200"
          />
          {cfg.file && (
            <button
              type="button"
              onClick={quitarAudio}
              className="mt-1.5 text-xs text-panel-muted underline transition hover:text-gray-100"
            >
              {t('chime.removeFile')}
            </button>
          )}
        </div>
      </fieldset>

      {error && <p className="mb-2 text-xs text-red-400">{tError(error)}</p>}

      <button
        type="button"
        onClick={guardar}
        disabled={busy}
        className="w-full rounded bg-panel-accent px-2 py-1.5 text-sm text-white transition hover:bg-blue-600 disabled:opacity-50"
      >
        {t('chime.save')}
      </button>
    </Modal>
  )
}
