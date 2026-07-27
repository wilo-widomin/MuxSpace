# US-013 · Extraer `CommandSelect` a `components/sidebar/CommandSelect.jsx`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 1 | fase-4-frontend | S1 |

## Historia

Como desarrollador del panel, quiero `CommandSelect` en su propio archivo:
es el desplegable que eligen los formularios de proyecto (nuevo y editar) y
no tiene nada que ver con el resto del sidebar.

## Criterios de aceptación

- [ ] `frontend/src/components/sidebar/CommandSelect.jsx` exporta
      `CommandSelect` con el mismo cuerpo y la misma firma
      (`{ value, onChange, commands }`).
- [ ] `Sidebar.jsx` lo importa; los **dos** usos (formulario de proyecto
      nuevo y de edición) siguen igual.
- [ ] Las cadenas i18n que use siguen resolviéndose (usa el hook `useT`;
      impórtalo en el archivo nuevo). `check-i18n` sin claves perdidas.
- [ ] `bun run build` verde, `lint` limpio.
- [ ] Comprobado a mano: crear un proyecto eligiendo un comando de la
      biblioteca y editar uno existente siguen funcionando, con la selección
      preseleccionada correcta al editar.

## Alcance técnico

- Crear `frontend/src/components/sidebar/CommandSelect.jsx`.
- Tocar `frontend/src/components/Sidebar.jsx`.

## Fuera de alcance

- Cambiar el control por un combobox con búsqueda o cualquier mejora de UX.
- Tocar `QuickCommandForm` o `DirectoryInput`, que se quedan donde están:
  el plan solo enumera seis componentes y estos no salen.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`exclusiva`.

## Notas para el agente

Comprueba si arrastra helpers definidos en `Sidebar.jsx`. Si es así, decide
entre moverlos también o importarlos, y **dilo en el PR**; lo que no vale es
duplicarlos.
