---
dominio: extension
accion: abrir-proyecto
actualizado: 2026-09-18
archivos:
  - extension/src/background.js
  - extension/src/lib/group.js
  - extension/src/lib/panel.js
  - extension/src/lib/sessions.js
  - extension/src/lib/storage.js
depende_de: [biblioteca/ejecutar-proyecto, espacios/_dominio]
---

# Abrir un proyecto

Un clic en el popup deja el escritorio montado: grupo de pestañas con el panel
en el espacio del proyecto y sus enlaces, y el proyecto con terminal viva.

## Flujo

1. Leer `panelOrigin` (sin él, error que manda a las opciones).
2. Comprobar la sesión con `GET /api/me`. Sin ella, poner la pestaña del
   panel delante y esperar a que el usuario entre; después se sigue por donde
   iba, sin pedirle otro clic.
3. Cargar los proyectos por el puente y cachearlos.
4. `ensureProjectReady`: pedir las sesiones, mover al espacio del proyecto las
   suyas que estén en otro (`sessionsToAdopt`) y lanzarlo si no le queda
   ninguna (`needsLaunch`). **Los fallos de este paso no abortan**: se acumulan
   como aviso.
5. Buscar el grupo existente y reconciliar: navegar la pestaña del panel al
   espacio correcto y abrir **solo** las pestañas que falten.
6. Agrupar, poner título y color, recordar el `groupId`, activar la primera
   pestaña del grupo y enfocar la ventana.

## Reglas

- Identidad del grupo: primero el `groupId` recordado (validado, porque el
  grupo puede haber muerto); si no, se busca un grupo **con el mismo título**.
- Si el grupo ya existe no se cierra ni se reordena nada; la única pestaña que
  se toca es la del panel, que se navega en vez de duplicarse.
- Las pestañas se comparan por origen + ruta (ignorando la barra final, pero
  distinguiendo la query).
- El color sale de un hash del id del proyecto: es estable, no aleatorio.

## Trampas

- Si se pierde el mapa `projectGroups` **y** se ha renombrado el proyecto, el
  vínculo se rompe y aparece un grupo duplicado.
- Desinstalar la extensión borra origen, caché y mapa; recargarla no.
- La pestaña puente que se abre en segundo plano se recicla o se cierra, pero
  si la apertura falla entre medias **se queda abierta**.
- Un proyecto sin espacio abre el panel sin espacio: solo se avisa.
