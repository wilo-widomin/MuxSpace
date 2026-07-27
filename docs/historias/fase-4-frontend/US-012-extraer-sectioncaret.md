# US-012 · Extraer `SectionCaret` a `components/sidebar/SectionCaret.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 1 | fase-4-frontend | S1 |

## Historia

Como desarrollador del panel, quiero `SectionCaret` en su propio archivo,
porque lo usan las cuatro secciones plegables del sidebar (comandos,
proyectos, pegar imagen, subir archivos) y dos de ellas se extraen en US-015
y US-016.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/SectionCaret.jsx` exporta
      `SectionCaret` con el mismo cuerpo y la misma firma (`{ open }`).
- [ ] `Sidebar.jsx` lo importa; los cuatro usos actuales siguen igual.
- [ ] Las clases de Tailwind se copian **literales** (el tamaño fijo de
      21 px y el `leading-none` están puestos a propósito para que el
      carácter `▾`/`▸` no descuadre la fila).
- [ ] `bun run build` verde, `check-i18n` sin cambios, `lint` limpio.
- [ ] Comprobado a mano: las cuatro secciones siguen mostrando el caret en
      la misma posición y el mismo tamaño, abierta y cerrada.

## Alcance técnico

- Crear `frontend/src/components/sidebar/SectionCaret.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.

## Fuera de alcance

- Sustituir el carácter por un SVG, animar la rotación o cualquier mejora
  visual.
- Tocar la lógica del acordeón (`openSection`), que se queda en `Sidebar.jsx`
  y se testea en US-017.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`exclusiva`.

## Notas para el agente

Es la extracción más pequeña de la serie. Si el diff crece más allá de mover
seis líneas y añadir un import, algo se está colando.
