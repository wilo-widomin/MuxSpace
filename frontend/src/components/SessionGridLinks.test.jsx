// El camino completo de los enlaces: del listado de proyectos a la badge.
//
// El test del tile prueba la badge con los enlaces ya en la mano. Este prueba
// el cableado que hay antes: la sesión trae el ID de su proyecto y el grid
// tiene que buscar los enlaces de ESE proyecto y dárselos a su tile. Con
// forma y datos reales (`/api/sessions` + `/api/projects`).
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LangProvider } from '../i18n/index.jsx'
import SessionGrid from './SessionGrid.jsx'

vi.mock('./XtermTerminal.jsx', () => ({ default: () => <div /> }))

const projects = [
  { id: '5a3497aa', title: 'MVP-LAB', commands: ['bun dev'], links: [
    { url: 'https://ejemplo.test/browse/mvp-lab/', title: 'Browse' },
  ] },
  { id: '0c5f90e3', title: 'MUXSPACE', commands: ['bun dev'], links: [] },
]

afterEach(cleanup)

it('la terminal de un proyecto con enlaces enseña sus badges', () => {
  render(
    <LangProvider>
      <SessionGrid
        openSessions={[
          { name: 'MVP-LAB', project: '5a3497aa' },
          { name: 'MUXSPACE', project: '0c5f90e3' },
          { name: 'TERM', project: null },
        ]}
        projects={projects}
        activeName={null}
        onSetActive={() => {}}
        onClose={() => {}}
        onKill={() => {}}
        onReorder={() => {}}
        commands={[]}
        layout="auto"
        focusedName={null}
        onSetFocused={() => {}}
      />
    </LangProvider>,
  )

  const badge = screen.getByRole('link', { name: 'Browse' })

  expect(badge).toHaveAttribute('href', 'https://ejemplo.test/browse/mvp-lab/')
  // Solo la suya: ni MUXSPACE (sin enlaces) ni TERM (sin proyecto) heredan nada.
  expect(screen.getAllByRole('link')).toHaveLength(1)
})
