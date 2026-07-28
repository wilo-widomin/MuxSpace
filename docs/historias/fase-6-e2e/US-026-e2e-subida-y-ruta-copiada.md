# US-026 · E2E: subir un archivo y comprobar la ruta copiada

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P3 | 3 | fase-6-e2e | S2 |

## Historia

Como usuario del panel, quiero un E2E que **suba un archivo y compruebe que
la ruta que se copia al portapapeles es la correcta**, incluida la
versión entrecomillada cuando lleva espacios, porque ese texto va directo a
una terminal y un entrecomillado mal hecho es un comando que hace otra cosa.

Cierra el backlog: junta el navegador de carpetas (US-003), la subida
(US-004) y `quotePath` (US-010/US-017) en un solo recorrido real.

## Criterios de aceptación

- [ ] Abrir la sección "subir archivos", elegir una carpeta con el navegador
      y subir un archivo desde el input de fichero.
- [ ] El archivo aparece en el historial y **existe en el disco** en la ruta
      esperada (compruébalo en el filesystem, no solo en el DOM).
- [ ] Copiar la ruta deja en el portapapeles **exactamente** la ruta
      absoluta, sin comillas, para un nombre sin caracteres especiales.
- [ ] Para un archivo cuyo nombre **lleva espacios**, la ruta copiada sale
      **entrecomillada**, con el escape que hace `quotePath`.
- [ ] Prueba también un nombre con `$` o comillas: el resultado copiado es
      seguro de pegar en un shell.
- [ ] Quitar la entrada del historial **no borra el archivo del disco**.
- [ ] Todo ocurre bajo las raíces del backend de pruebas (un directorio
      temporal). Ni un byte fuera.
- [ ] Sin errores de CSP en consola durante el recorrido.

## Alcance técnico

- Un archivo de test más en el `e2e/` de US-024, reutilizando su andamiaje.
- El portapapeles en Playwright necesita permisos
  (`context.grantPermissions(['clipboard-read', 'clipboard-write'])`) y solo
  funciona bien en Chromium. Si el fallback del `textarea` oculto es lo que
  se dispara, prueba **ese** camino y déjalo dicho en el test.

## Fuera de alcance

- El pegado de imágenes (`PasteForClaude`): es otro flujo y el plan solo
  pide tres casos E2E.
- Subir varios archivos a la vez o arrastrar y soltar.
- Probar los límites de tamaño: eso está cubierto en US-004, donde es barato.

## Dependencias

US-024.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`.

## Notas para el agente

- El corazón de esta US es el **entrecomillado**. Si solo compruebas la
  ruta simple, has probado la parte que nunca falla.
- Comprobar el filesystem además del DOM es lo que separa este test de una
  prueba de maquetación.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-28 16:57:02 UTC
- Fin:    2026-07-28 17:03:24 UTC
- Tiempo transcurrido: 00:06:21 (HH:mm:ss)
- PR:     (sin PR)
- Estado: in-review
