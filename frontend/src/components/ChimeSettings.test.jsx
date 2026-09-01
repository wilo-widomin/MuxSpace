// Los ajustes de la campanilla: elegir sonido, inventarse uno y subir el tuyo.
//
// Lo que se demuestra aquí es lo que el usuario hace con el diálogo. La
// síntesis en sí no se prueba: jsdom no tiene WebAudio y comprobar que se
// creó un oscilador no dice nada sobre si eso suena bien, que es la única
// pregunta que importa y solo se responde con los oídos.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api.js'
import { LangProvider } from '../i18n/index.jsx'
import en from '../i18n/locales/en.json'
import { ChimeSettings } from './ChimeSettings.jsx'

// El navegador de los tests no reproduce nada; lo que interesa es qué se
// guarda, no qué se oye.
vi.mock('../lib/chime.js', async (original) => ({
  ...(await original()),
  configure: vi.fn(),
  previewChime: vi.fn(),
}))

const AJUSTE = {
  mode: 'preset',
  preset: 'bell',
  volume: 0.3,
  muted: false,
  notes: [],
  timbre: 'bell',
  file: null,
}

function abrir(cfg = AJUSTE) {
  vi.spyOn(api, 'getChime').mockResolvedValue({ ...cfg })
  render(
    <LangProvider>
      <ChimeSettings onClose={() => {}} />
    </LangProvider>,
  )
  return screen.findByText(en['chime.title'])
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(cleanup)

describe('Ajustes de la campanilla', () => {
  it('ofrece los sonidos del panel y guarda el que se elija', async () => {
    await abrir()
    const guardar = vi.spyOn(api, 'saveChime').mockResolvedValue({
      ...AJUSTE,
      preset: 'marimba',
    })

    fireEvent.click(screen.getByLabelText(en['chime.preset.marimba']))
    fireEvent.click(screen.getByText(en['chime.save']))

    await waitFor(() =>
      expect(guardar).toHaveBeenCalledWith(
        expect.objectContaining({ mode: 'preset', preset: 'marimba' }),
      ),
    )
  })

  it('«el mío» empieza copiando el sonido que estaba puesto', async () => {
    // Trastear desde algo que ya suena bien, no desde una lista vacía: es la
    // diferencia entre editar y tener que componer.
    await abrir({ ...AJUSTE, preset: 'two-tones' })
    fireEvent.click(screen.getByLabelText(en['chime.custom']))

    const tonos = screen.getAllByLabelText(en['chime.freq'])
    expect(tonos).toHaveLength(2)
    expect(tonos[0].value).toBe('880')
  })

  it('no deja quedarse sin ninguna nota', async () => {
    // Un aviso mudo se confunde con uno estropeado.
    await abrir({
      ...AJUSTE,
      mode: 'custom',
      notes: [{ freq: 880, delay: 0, duration: 0.4 }],
    })
    expect(screen.getByLabelText(en['chime.removeNote'])).toBeDisabled()
  })

  it('añadir una nota la encadena detrás de la última', async () => {
    await abrir({
      ...AJUSTE,
      mode: 'custom',
      notes: [{ freq: 880, delay: 0, duration: 0.4 }],
    })
    fireEvent.click(screen.getByText(en['chime.addNote']))

    const entradas = screen.getAllByLabelText(en['chime.delay'])
    expect(entradas).toHaveLength(2)
    expect(Number(entradas[1].value)).toBeGreaterThan(0)
  })

  it('silenciar no borra el sonido elegido', async () => {
    await abrir({ ...AJUSTE, preset: 'marimba' })
    fireEvent.click(screen.getByLabelText(en['chime.enabled']))

    // Sigue marcado: al volver a activarlo suena lo de antes, no hay que
    // elegirlo otra vez.
    expect(screen.getByLabelText(en['chime.preset.marimba'])).toBeChecked()
  })

  it('sin archivo propio, esa opción no se puede elegir', async () => {
    await abrir()
    expect(screen.getByText(en['chime.noFile'])).toBeInTheDocument()
    expect(screen.getByLabelText(en['chime.noFile'])).toBeDisabled()
  })

  it('subir un audio lo deja sonando sin un paso más', async () => {
    await abrir()
    vi.spyOn(api, 'uploadChimeAudio').mockResolvedValue({
      ...AJUSTE,
      mode: 'file',
      file: 'custom.mp3',
    })

    const fichero = new File(['bytes'], 'campana.mp3', { type: 'audio/mpeg' })
    fireEvent.change(document.querySelector('input[type="file"]'), {
      target: { files: [fichero] },
    })

    await waitFor(() =>
      expect(
        screen.getByLabelText(en['chime.fileNamed'].replace('{name}', 'custom.mp3')),
      ).toBeChecked(),
    )
  })

  it('un error del servidor se enseña traducido', async () => {
    await abrir()
    const { ApiError } = await import('../api.js')
    vi.spyOn(api, 'saveChime').mockRejectedValue(
      new ApiError(400, { code: 'err.chime_no_notes' }),
    )

    fireEvent.click(screen.getByText(en['chime.save']))
    expect(await screen.findByText(en['err.chime_no_notes'])).toBeInTheDocument()
  })
})
