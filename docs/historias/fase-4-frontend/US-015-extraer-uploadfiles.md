# US-015 · Extraer `UploadFiles` a `components/sidebar/UploadFiles.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-4-frontend | S2 |

## Historia

Como desarrollador del panel, quiero la sección "subir archivos" en su propio
archivo. Son ~240 líneas: elección de carpeta, subida, historial, copiado de
rutas y manejo de errores. Es la sección más grande del sidebar y la que
consume el endpoint que más superficie de seguridad tiene.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/UploadFiles.jsx` exporta
      `UploadFiles` con la misma firma (`{ open, onToggle }`).
- [ ] Importa `SectionCaret` (US-012), `DirBrowserModal` (US-014) y
      `quotePath` desde `lib/paths` (US-010). Ninguna copia local.
- [ ] `Sidebar.jsx` lo importa y su único uso sigue igual, con el acordeón
      (`open={openSection === 'upload'}`) funcionando como antes.
- [ ] Todas las cadenas i18n siguen resolviéndose; `check-i18n` sin claves
      perdidas ni nuevas huérfanas.
- [ ] `bun run build` verde, `lint` limpio.
- [ ] Comprobado a mano en el navegador, el flujo entero: elegir carpeta →
      subir un archivo → ver la ruta en el historial → copiarla → quitarla
      del historial. Y un caso de error real: subir un nombre inválido y ver
      el mensaje traducido.
- [ ] La ruta copiada de un archivo **con espacios** sigue saliendo
      entrecomillada.
- [ ] El fallback de copiado (el `textarea` oculto, para navegadores sin
      `navigator.clipboard`) se mueve con el componente y sigue funcionando.

## Alcance técnico

- Crear `frontend/src/components/sidebar/UploadFiles.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.

## Fuera de alcance

- Cambiar la UX de subida (arrastrar y soltar, barra de progreso, múltiples
  archivos).
- Tocar `/api/upload` en el backend.

## Dependencias

US-010, US-012, US-014.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`.

## Notas para el agente

- Es la extracción más larga; el riesgo es dejarse un trozo de estado en
  `Sidebar.jsx`. Repasa que no quede ningún `useState` huérfano allí.
- Después de esta US, `Sidebar.jsx` debería haber adelgazado ~240 líneas.
  Comprueba el `wc -l` antes y después y ponlo en el PR: es la métrica que
  justifica toda la fase 4.
