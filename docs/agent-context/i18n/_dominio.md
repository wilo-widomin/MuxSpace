---
dominio: i18n
actualizado: 2026-08-28
archivos:
  - frontend/src/i18n/index.jsx
  - frontend/src/i18n/locales/es.json
  - frontend/src/i18n/locales/en.json
  - frontend/src/i18n/locales/de.json
  - frontend/src/i18n/locales/fr.json
  - frontend/src/i18n/locales/it.json
  - frontend/src/i18n/locales/pt.json
  - scripts/check-i18n.js
depende_de: [acceso/_dominio]
---

# i18n

Módulo propio (no react-i18next): claves **planas**, interpolación `{name}` y
plurales por `Intl.PluralRules`, en 6 idiomas. El backend no traduce nada: emite
`{code, params, technical}` y el frontend resuelve el texto, así que el catálogo
vive en un solo sitio.

## Cómo se usa

- `const { t, tError, lang, setLang } = useT()`. `useT()` lanza si no hay
  `LangProvider` encima; lo monta `frontend/src/main.jsx`.
- `t('form.create_session')`, `t('err.image_too_large', { mb: 5 })`. Un
  placeholder sin valor se queda literal en pantalla, no se vacía.
- **Plural**: la entrada del JSON es un objeto en vez de un string y se dispara
  con el parámetro `count`, cuyo nombre es fijo. La forma la elige
  `Intl.PluralRules`; si esa forma no existe, cae a `other`.
- Un error del backend se pinta **siempre** con `tError(err)`, nunca con
  `err.message`: `tError` traduce el `code` con sus `params` y añade el
  `technical` entre paréntesis si lo hay.

## Convenio de claves

Plano, `zona.snake_case`. Zonas vigentes: `app.`, `clock.`, `compose.`,
`dashboard.`, `err.`, `form.`, `grid.`, `lang.`, `login.`, `modal.`, `paste.`,
`pause.`, `sidebar.`, `spaces.`, `term.`, `tile.`, `transcript.`, `upload.`.

## Invariantes

- **`es.json` es la fuente de verdad** y se escribe primero: añadir una clave
  obliga a tocar los seis archivos en el mismo commit.
- Una clave que falta en un idioma degrada al español, no a la clave cruda.
- El idioma se elige por `localStorage` (`muxspace:lang`), luego por el del
  navegador, luego español.

## Acciones documentadas

- [Añadir una clave](anadir-una-clave.md)

## Trampas

- El `<title>` no se pone en el proveedor de idioma sino en `App.jsx`: el
  efecto del hijo ganaría al del padre.
- `grid.layout_auto` y compañía se piden con una clave construida
  (`` t(`grid.layout_${modo}`) ``): no las borres por «sin uso».
- El verificador **solo detecta comillas simples**: `t("clave")` con dobles no
  lo ve — ni para avisar de que no se usa, ni para cazar que no existe.
- La forma plural `many` está silenciada a propósito (solo la exigiría la
  notación compacta de números, que aquí no se usa).
