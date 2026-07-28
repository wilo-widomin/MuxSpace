# US-016 · Extraer `PasteForClaude` a `components/sidebar/PasteForClaude.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-4-frontend | S2 |

## Historia

Como desarrollador del panel, quiero la sección "pegar imagen" en su propio
archivo. Son ~270 líneas: captura del portapapeles, subida, galería de
miniaturas, borrado y copiado de rutas.

Cierra la serie de extracciones de `Sidebar.jsx`.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/PasteForClaude.jsx` exporta
      `PasteForClaude` con la misma firma (`{ open, onToggle }`).
- [ ] Importa `SectionCaret` (US-012) y `quotePath` desde `lib/paths`
      (US-010). Ninguna copia local.
- [ ] `Sidebar.jsx` lo importa y su uso sigue igual, con el acordeón
      (`open={openSection === 'paste'}`) funcionando como antes.
- [ ] `check-i18n` sin claves perdidas; `bun run build` verde; `lint` limpio.
- [ ] Comprobado a mano en el navegador: pegar una captura con `Ctrl+V`,
      verla aparecer en la galería, **que la miniatura cargue** (viene de
      `/api/pastes/{filename}`, sujeta a la CSP `img-src 'self' data:` de la
      fase 0), copiar su ruta y borrarla.
- [ ] La retención sigue en 5 capturas: al pegar la sexta desaparece la más
      antigua.
- [ ] Tras el cambio, `Sidebar.jsx` baja de **2.572 a menos de 1.700
      líneas**. Pon el `wc -l` final en el PR.

## Alcance técnico

- Crear `frontend/src/components/sidebar/PasteForClaude.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.

## Fuera de alcance

- Cambiar la UX de pegado (arrastrar imágenes, previsualización grande).
- Tocar `/api/paste-image` en el backend.
- Seguir troceando lo que queda en `Sidebar.jsx` (`SpacesBar`,
  `DirectoryInput`, `QuickCommandForm`, `LanguagePicker`, los iconos): no
  está en el plan. Si crees que hace falta, propónlo, no lo hagas.

## Dependencias

US-010, US-012.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`.

## Notas para el agente

Esta sección es la que el usuario usa para compartir capturas con Claude
(las deja en `backend/data/pastes/`). Si algo se rompe aquí, se nota en el
uso diario: la comprobación manual en el navegador no es opcional.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-28 11:05:51 UTC
- Fin:    2026-07-28 11:08:27 UTC
- Tiempo transcurrido: 00:02:36 (HH:mm:ss)
- PR:     (sin PR)
- Estado: in-progress
