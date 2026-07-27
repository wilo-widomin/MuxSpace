# US-022 · i18n: claves muertas y plurales `many`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 1 | fase-3-ci | S1 |

> El plan la lista en la Fase 5, pero **US-009 depende de ella**: el gate de
> CI no puede activar `check-i18n` como error mientras el script escupa
> avisos. Vive en la fase 3 por eso; el número se conserva para no
> renumerar el resto del backlog.

## Historia

Como responsable del panel, quiero **dejar `check-i18n` sin avisos**, porque
US-009 lo convierte en un gate bloqueante del CI y hoy escupe once líneas de
ruido. Un chequeo con avisos permanentes es un chequeo que nadie lee.

## Criterios de aceptación

- [ ] Borradas las **3 claves sin uso** en los 6 idiomas:
      `grid.layout_auto`, `grid.layout_cols`, `grid.layout_rows`.
- [ ] Antes de borrar, comprobado con `grep` que efectivamente no se usan
      (ni por concatenación dinámica de claves, que `check-i18n` no detecta).
- [ ] Cerrados los avisos de plural `many` en `es`, `fr`, `it` y `pt` para
      `sidebar.windows` y `spaces.confirm_delete`. Según
      [`docs/i18n.md`](../../i18n.md) el runtime cae a `other`, así que la
      decisión correcta es **silenciar ese aviso concreto** en
      `scripts/check-i18n.js`, no inventar formas plurales que ningún idioma
      de la lista usa de verdad.
- [ ] Si en vez de silenciarlo decides añadir las formas, que sean
      **correctas** para cada idioma y quede justificado en el PR. Una de las
      dos vías, no las dos a medias.
- [ ] `cd frontend && bun run check-i18n` termina **sin avisos y sin
      errores**.
- [ ] El script sale con **código distinto de 0** cuando falta una clave.
      Compruébalo borrando una temporalmente; es lo que hace que el gate de
      US-009 sirva de algo.
- [ ] `bun run build` verde.
- [ ] `docs/i18n.md` actualizado con la decisión sobre los plurales.

## Alcance técnico

- `frontend/src/i18n/locales/*.json` (los 6).
- `scripts/check-i18n.js`.
- `docs/i18n.md`.

## Fuera de alcance

- Añadir idiomas o traducir cadenas nuevas.
- Reorganizar la estructura de claves (hoy son planas; que sigan planas).
- Enganchar el script al CI: eso es US-009.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`exclusiva` respecto a cualquier US que añada claves i18n.

## Notas para el agente

- Ojo con el orden: si borras claves mientras otra US está añadiendo, el
  merge se lía. Por eso es exclusiva.
- El criterio que de verdad importa es el del **código de salida**: un
  `check-i18n` que siempre devuelve 0 no bloquea nada, y todo el valor de
  US-009 depende de que este bloquee.
