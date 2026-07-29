/**
 * Cada etiqueta de formulario llega a su campo.
 *
 * No es un test de maquetación: `getByLabel` consulta el **árbol de
 * accesibilidad**, el mismo que usa un lector de pantalla. Que encuentre el
 * campo significa que la etiqueta está de verdad conectada a él —por `for`/`id`
 * o envolviéndolo—, y no solo puesta encima.
 *
 * Existe porque la verificación por mutación lo pidió: desatar la etiqueta del
 * directorio de un proyecto no ponía en rojo ningún test, porque ningún
 * recorrido abría ese modal. Un arreglo sin test que lo sujete dura hasta el
 * siguiente refactor.
 *
 * Recorre los tres formularios del panel y comprueba TODAS sus etiquetas, así
 * que también cubre las que ningún otro test toca.
 */
import { T, entrar, expect, test } from './fixtures.js'

/** Los tres modales del sidebar, con las etiquetas que debe tener cada uno. */
const FORMULARIOS = [
  {
    abrir: T['sidebar.new_session'],
    titulo: T['form.new_session_title'],
    etiquetas: [T['form.session_name_label'], T['form.start_command_label']],
  },
  {
    abrir: T['sidebar.new_command'],
    titulo: T['form.new_command_title'],
    etiquetas: [T['form.name_optional_label'], T['form.command_label']],
  },
  {
    abrir: T['sidebar.new_project'],
    titulo: T['form.new_project_title'],
    etiquetas: [T['form.title_label'], T['form.directory_label']],
  },
]

for (const form of FORMULARIOS) {
  test(`las etiquetas de «${form.titulo}» llegan a su campo`, async ({
    page,
    entorno,
  }) => {
    await entrar(page, entorno)
    await page.getByRole('button', { name: form.abrir }).click()
    // Se espera por la primera etiqueta y no por el título del modal: el
    // título coincide con el `title` del botón que lo abre ("Nueva sesión"
    // está en los dos sitios) y el localizador daría ambigüedad.
    await expect(page.getByLabel(form.etiquetas[0])).toBeVisible()

    for (const etiqueta of form.etiquetas) {
      const campo = page.getByLabel(etiqueta)
      await expect(
        campo,
        `la etiqueta «${etiqueta}» no llega a ningún campo: es texto suelto ` +
          'encima del control, no su etiqueta',
      ).toHaveCount(1)
      // Y llega a un campo EDITABLE, no a un `<div>` cualquiera que se llame
      // igual: se escribe en él y se comprueba que lo recoge.
      await campo.fill('prueba-de-accesibilidad')
      await expect(campo).toHaveValue('prueba-de-accesibilidad')
    }
  })
}

test('el campo de contraseña del login también está etiquetado', async ({
  page,
}) => {
  // Va aparte porque el login es la única pantalla que se ve sin sesión, y
  // porque es la que más gente usa con el teclado.
  for (const etiqueta of [T['login.username'], T['login.password']]) {
    const campo = page.getByLabel(etiqueta)
    await expect(campo, `«${etiqueta}» no llega a ningún campo`).toHaveCount(1)
    await campo.fill('x')
    await expect(campo).toHaveValue('x')
  }
})
