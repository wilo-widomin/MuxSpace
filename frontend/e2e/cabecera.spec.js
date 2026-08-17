/**
 * La cabecera del sidebar aguanta el ancho mínimo.
 *
 * Existe por dos incidentes reales, y los dos empezaron igual: añadir un
 * icono más.
 *
 * 1. Al añadir el cronómetro, los últimos botones se salieron de la barra.
 *    Seguían existiendo y respondiendo a `getByRole`, así que ningún test
 *    unitario podía verlo; lo que fallaba era que el clic aterrizaba donde el
 *    botón ya no estaba. Cinco E2E en rojo por un `flex` sin `wrap`.
 * 2. Con el `wrap` puesto, al estrechar el sidebar la cabecera se repartía en
 *    TRES líneas con el título encajado en medio.
 *
 * Por eso aquí se miden dos cosas que solo se ven renderizando: que la
 * cabecera cabe en dos filas y que ningún control queda fuera de la barra.
 */
import { T, entrar, expect, test } from './fixtures.js'

// El mínimo al que `clampSidebarWidth` deja encoger el sidebar (App.jsx).
const ANCHO_MINIMO = 220
// Dos filas de iconos con su padding. Tres se pasan de aquí.
const ALTO_DOS_FILAS = 90

test('al ancho mínimo cabe en dos filas y ningún control se sale', async ({
  page,
  entorno,
}) => {
  await entrar(page, entorno)
  await page.evaluate(
    (ancho) => localStorage.setItem('muxspace-sidebar-width', String(ancho)),
    ANCHO_MINIMO,
  )
  await page.reload()
  await page.getByRole('button', { name: T['sidebar.new_session'] }).waitFor()

  const cabecera = page.locator('header').first()
  const caja = await cabecera.boundingBox()

  expect(
    caja.height,
    'la cabecera se ha ido a tres filas: sobran iconos o falta apretarlos',
  ).toBeLessThan(ALTO_DOS_FILAS)

  const controles = cabecera.locator('button, a')
  const cuantos = await controles.count()
  expect(cuantos, 'no se han encontrado los controles de la cabecera').toBeGreaterThan(
    5,
  )
  for (let i = 0; i < cuantos; i++) {
    const b = await controles.nth(i).boundingBox()
    expect(
      b.x >= caja.x - 0.5 && b.x + b.width <= caja.x + caja.width + 0.5,
      `el control ${i} queda fuera de la barra: existe, pero no se puede pulsar`,
    ).toBe(true)
  }
})
