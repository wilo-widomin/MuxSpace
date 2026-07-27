# US-014 · Extraer `DirBrowserModal` a `components/sidebar/DirBrowserModal.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 2 | fase-4-frontend | S2 |

## Historia

Como desarrollador del panel, quiero el navegador de carpetas en su propio
archivo. Son ~140 líneas con estado propio (ruta actual, subcarpetas,
creación de carpeta) que no tienen relación con el resto del sidebar, y es el
componente que habla con los endpoints cuyo perímetro fija US-003.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/DirBrowserModal.jsx` exporta
      `DirBrowserModal` con la misma firma
      (`{ initialPath, onClose, onPick }`).
- [ ] Importa `Modal` desde `./Modal` (US-011), no una copia.
- [ ] `Sidebar.jsx` (o `UploadFiles`, según dónde quede el uso) lo importa;
      el único punto de uso actual sigue igual.
- [ ] Las llamadas a la API (`dirBrowse`, `dirCreate`) siguen viniendo de
      `api.js`, sin duplicar rutas.
- [ ] El manejo de errores sigue traduciendo por clave (`tError`), sin
      inventar textos.
- [ ] `bun run build` verde, `check-i18n` sin claves perdidas, `lint` limpio.
- [ ] Comprobado a mano en el navegador, con el modal abierto desde "subir
      archivos": navegar hacia dentro, subir un nivel, crear una carpeta,
      elegir una carpeta, y el caso de error (carpeta fuera de las raíces →
      mensaje traducido, no un stack).

## Alcance técnico

- Crear `frontend/src/components/sidebar/DirBrowserModal.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.

## Fuera de alcance

- Cambiar el flujo del navegador de carpetas (breadcrumbs, favoritos,
  teclado).
- Tocar `dir_suggestions.py` en el backend.

## Dependencias

US-011.

## Rigor

`estándar`. Es la primera extracción con estado propio y llamadas a la API:
merece la comprobación manual completa.

## Concurrencia

`exclusiva`.

## Notas para el agente

- Si el componente usa algo definido más abajo en `Sidebar.jsx` (iconos,
  helpers), resuélvelo con imports; nada de copiar.
- El diff sigue siendo un movimiento. Lo único que puede aparecer de nuevo
  son las líneas de `import`/`export`.
