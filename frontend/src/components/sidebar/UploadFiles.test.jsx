// De dónde sale la carpeta destino de las subidas.
//
// Es lógica que no se ve: el destino no lo escribe el usuario, se resuelve
// entre tres candidatos (lo recordado para ESTE espacio, `~/tmp`, y la raíz
// configurada como último recurso) y solo se pinta el resultado. Un E2E no
// puede afirmar gran cosa aquí porque su backend de pruebas tiene las raíces
// en un temporal, donde `~/tmp` nunca existe.
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../../i18n/index.jsx'
import { UploadFiles } from './UploadFiles.jsx'

const dirBrowse = vi.fn()

vi.mock('../../api.js', async () => {
  const real = await vi.importActual('../../api.js')
  return {
    ...real,
    api: {
      dirBrowse: (p) => dirBrowse(p),
      listUploads: () => Promise.resolve([]),
    },
  }
})

/** Responde como el backend: devuelve la ruta que le piden, ya resuelta. */
const carpetaValida = (p) =>
  Promise.resolve({ path: p || '/raiz', parent: null, dirs: [] })

function montar(space) {
  localStorage.setItem('muxspace:lang', 'es')
  return render(
    <LangProvider>
      <UploadFiles open onToggle={() => {}} space={space} />
    </LangProvider>,
  )
}

describe('carpeta destino de las subidas', () => {
  beforeEach(() => {
    localStorage.clear()
    dirBrowse.mockReset()
    dirBrowse.mockImplementation(carpetaValida)
  })
  afterEach(cleanup)

  it('sin nada recordado, va a ~/tmp', async () => {
    montar('esp-1')
    await waitFor(() => expect(dirBrowse).toHaveBeenCalledWith('~/tmp'))
    expect(await screen.findByText('~/tmp')).toBeTruthy()
  })

  it('usa lo que se recordó PARA ESE espacio', async () => {
    localStorage.setItem('muxspace:upload-dir:esp-1', '~/proyectos/uno')
    localStorage.setItem('muxspace:upload-dir:esp-2', '~/proyectos/dos')

    montar('esp-2')
    await waitFor(() => expect(dirBrowse).toHaveBeenCalledWith('~/proyectos/dos'))
    // Y no se contamina con el del otro espacio, que es el fallo que este
    // test existe para pillar.
    expect(dirBrowse).not.toHaveBeenCalledWith('~/proyectos/uno')
  })

  it('si la carpeta recordada ya no vale, cae a la raíz configurada', async () => {
    // Carpeta borrada desde la última vez, o sacada de las raíces. Sin este
    // respaldo la subida fallaría con el archivo ya elegido.
    localStorage.setItem('muxspace:upload-dir:esp-1', '~/borrada')
    dirBrowse.mockImplementation((p) =>
      p === '' ? carpetaValida('/raiz') : Promise.reject(new Error('no existe')),
    )

    montar('esp-1')
    await waitFor(() => expect(dirBrowse).toHaveBeenCalledWith(''))
    expect(await screen.findByText('/raiz')).toBeTruthy()
  })

  it('cambiar de espacio cambia el destino', async () => {
    localStorage.setItem('muxspace:upload-dir:esp-2', '~/proyectos/dos')
    const { rerender } = montar('esp-1')
    await waitFor(() => expect(dirBrowse).toHaveBeenCalledWith('~/tmp'))

    rerender(
      <LangProvider>
        <UploadFiles open onToggle={() => {}} space="esp-2" />
      </LangProvider>,
    )
    await waitFor(() => expect(dirBrowse).toHaveBeenCalledWith('~/proyectos/dos'))
  })
})
