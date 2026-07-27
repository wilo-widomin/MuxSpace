# US-011 · Extraer `Modal` a `components/sidebar/Modal.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 1 | fase-4-frontend | S1 |

## Historia

Como desarrollador del panel, quiero `Modal` en su propio archivo, porque es
la primitiva de la que cuelgan cinco diálogos del sidebar y el
`DirBrowserModal` que se extrae en US-014.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/Modal.jsx` exporta `Modal` con el
      mismo cuerpo y la misma firma (`{ title, onClose, children,
      panelClassName = 'max-w-md' }`).
- [ ] `Sidebar.jsx` lo importa; los **cinco** usos actuales (nueva sesión,
      nuevo comando, editar comando, nuevo proyecto, editar proyecto) siguen
      igual, incluidos los que pasan `panelClassName="max-w-lg"`.
- [ ] `bun run build` verde, `check-i18n` sin cambios, `lint` limpio.
- [ ] El diff es un corta y pega: sin renombrados, sin reformateo, sin
      cambiar clases de Tailwind.
- [ ] Comprobado a mano: los cinco diálogos abren, cierran con la X y con
      Escape (si ya lo hacían), y el panel ancho sigue siendo ancho.

## Alcance técnico

- Crear `frontend/src/components/sidebar/Modal.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.
- Si `Modal` usa algún icono definido más abajo en `Sidebar.jsx`
  (`CloseIcon`), muévelo con él o impórtalo; **no lo dupliques**. Decide y
  explica en el PR.

## Fuera de alcance

- Cambiar el comportamiento del modal (foco, scroll lock, accesibilidad).
  Si detectas algo, anótalo; no es esta US.
- Extraer los iconos como colección (`components/icons.jsx`): es otro
  refactor y no está en el plan.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`exclusiva`.

## Notas para el agente

Mismo contrato que US-010: movimiento mecánico, cero cambios de
comportamiento.
