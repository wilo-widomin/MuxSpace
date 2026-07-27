# US-010 · Extraer `quotePath` a `lib/paths.js`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 1 | fase-4-frontend | S1 |

## Historia

Como desarrollador del panel, quiero `quotePath` **fuera de `Sidebar.jsx`**,
porque es lógica pura, la usan dos componentes distintos y es lo primero que
US-017 va a querer testear sin montar React.

Primera de la serie de extracciones. Marca el patrón que siguen las demás:
**movimiento mecánico, cero cambios de comportamiento**.

## Criterios de aceptación

- [ ] `frontend/src/lib/paths.js` exporta `quotePath` con **el mismo cuerpo,
      byte a byte**, incluido su comentario (explica por qué se entrecomilla
      y por qué se escapan `"`, `$`, `` ` `` y `\`).
- [ ] `Sidebar.jsx` ya no define `quotePath` y la importa desde `lib/paths`.
- [ ] Los 6 puntos de uso actuales siguen funcionando (dos en
      `PasteForClaude`, dos en `UploadFiles`, dos en el render de rutas).
- [ ] `bun run build` verde y `bun run check-i18n` sin cambios.
- [ ] `bun run lint` limpio (si US-008 ya está mergeada).
- [ ] El diff **no** contiene ningún cambio de lógica, formato ni nombres.
      `git diff` tiene que leerse como un corta y pega.
- [ ] Comprobado a mano en el navegador: copiar la ruta de una captura y la
      de un archivo subido siguen dando el mismo texto que antes, incluido
      el caso con espacios.

## Alcance técnico

- Crear `frontend/src/lib/paths.js`.
- Tocar `frontend/src/components/Sidebar.jsx` (borrar la función, añadir el
  import).

## Fuera de alcance

- Tests de `quotePath` (los trae US-017).
- Cambiar la implementación, aunque veas algo mejorable. Si lo ves,
  anótalo en el PR.
- Mover cualquier otra cosa.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`exclusiva`. Toca `Sidebar.jsx`, igual que US-011 a US-016.

## Notas para el agente

- La extracción es prerrequisito **práctico** de poder testear: `Sidebar.jsx`
  tiene 2.572 líneas y es el archivo que más se toca del proyecto.
- Un PR de extracción con un cambio funcional escondido es peor que no
  extraer. Si algo no se puede mover sin tocarlo, dilo y para.
