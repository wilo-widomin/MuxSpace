---
dominio: biblioteca
accion: textos-rapidos
actualizado: 2026-09-07
archivos:
  - backend/library_store.py
  - backend/main.py
  - frontend/src/components/SnippetSettings.jsx
  - frontend/src/components/SettingsMenu.jsx
  - frontend/src/components/TerminalTile.jsx
depende_de: [terminal/_dominio, atencion/_dominio]
---

# Textos rápidos

Texto guardado que se **escribe** en la terminal. Existe para lo que se teclea
a menudo desde una tableta y no es un comando de shell: el nombre de una skill,
una orden a un agente que ya corre dentro. Cada texto decide si además **se
envía** (`submit`) o se queda en el prompt para seguir escribiendo.

## Flujo

1. Se gestionan en **Ajustes → Textos rápidos** (`SnippetSettings`), CRUD
   contra `/api/snippets`.
2. En la cabecera de cada terminal, el botón de la **tecla** (`KeycapIcon`,
   junto al ▶) abre la lista.
3. Elegir uno dispara `setPaste({token, text, submit})` → `XtermTerminal` hace
   `term.paste(texto)` y, si `submit`, un `term.input('\r')` aparte.

## Reglas

- `Snippet` = `id`, `label`, `text`, `submit`. Vive en `library.json` bajo
  `snippets`, junto a comandos y proyectos.
- `submit` por defecto es `false`, también al leer un texto guardado antes de
  que el campo existiera: no enviar es lo que hacían.
- Sin `label` se usa **la primera línea** del texto truncada a 60: la lista es
  de una fila por texto y un snippet puede tener varias líneas.
- Máximo `_MAX_SNIPPET_TEXT` (2000) caracteres. Para pegar algo largo está el
  redactor de la terminal, que además guarda borrador.
- El desplegable de la terminal **no tiene filtro**, al revés que el de
  comandos: son pocos, y en una tableta un filtro significa abrir el teclado.

## Trampas

- **El Enter va por `term.input('\r')`, nunca dentro del texto del `paste`.**
  Metido en el texto se quedaría dentro del pegado con corchetes y la TUI lo
  leería como un salto de línea más — lo contrario de enviar.
- **No hay endpoint de "enviar" y es deliberado.** Mandarlo por el backend con
  `send-keys` obligaría a decidir ahí si lleva Enter, y todo el sentido de la
  feature es que no lo lleve. Si algún día hace falta enviarlo, eso ya es un
  Comando de la biblioteca.
- La lista que ven las terminales abiertas la carga `App` (`loadCommands`).
  Editar en Ajustes la refresca vía `onSnippetsChanged`; sin esa llamada el
  desplegable seguiría enseñando lo de antes hasta recargar la página.
- El formato en disco lo fija `test_biblioteca_el_formato_en_disco_es_el_declarado`:
  añadir una clave al JSON obliga a tocar ese test a mano, a propósito.
