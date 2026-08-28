---
dominio: jornada
accion: contar-la-jornada
actualizado: 2026-08-28
archivos:
  - backend/worklog.py
  - backend/config.py
  - frontend/src/worklog.js
  - frontend/src/useWorkClock.js
  - frontend/src/components/Dashboard.jsx
depende_de: [espacios/_dominio]
---

# Contar la jornada

Lo escrito son ranuras de 30 s; el total depende del **modo de lectura**, y el
mismo dato se cuenta de dos maneras distintas.

## Los dos modos

- **`measured`** — suma solo lo medido, más el **puente de continuidad**: al
  leer se rellenan los huecos de hasta `WORKLOG_BRIDGE_MIN` (10 min por
  defecto) entre dos ranuras del mismo espacio que sean consecutivas
  *globalmente*. Si otro proyecto reclamó algo en medio, no hay puente; sin
  ranura posterior, tampoco.
- **`workday`** (por defecto) — cuenta el **día local entero**, de la primera a
  la última señal, menos las pausas. Las señales solo deciden **en qué
  proyecto** cae cada tramo, repartiendo por cercanía temporal y desempatando a
  favor de las señales tuyas. Tope `WORKLOG_MAX_DAY_HOURS` (10 h) aplicado
  sobre lo contado, no sobre el horario: al revés castigaría a quien marca
  pausas.

## Qué decide que estás trabajando

En el cliente (`frontend/src/worklog.js`): hay foco en el documento y la última
entrada es de hace menos de 3 minutos. Si no, y el cronómetro manual está
encendido, cuenta como manual salvo que haya caducado (30 min, renovables con
cualquier tecla) o que el detector de inactividad diga que no estás.

Latido cada 30 s desde `useWorkClock.js`, con oyentes pasivos que solo escriben
en refs (un `mousemove` que provoque render haría inusable el arrastre).

## Reglas del dashboard

- `total_seconds` = número de ranuras × 30.
- La **media es por días con trabajo**, no por días del calendario.
- Filtrar por espacio filtra el resumen entero (total, días y media), y se
  aplica **después** del puente.
- Resumen, bloques y pausas se piden en paralelo **con el mismo modo**: si
  difirieran, la lista de abajo no sumaría el total de arriba.

## Trampas

- El agrupado por día usa el desfase local **en minutos** que manda el cliente
  en cada consulta (acotado a ±14 h). Sin él, la jornada se partiría a las 2:00.
- Un bloque puede acabar y el siguiente empezar en el mismo instante: el fin es
  exclusivo (inicio de la última ranura + 30 s).
- Con el interruptor manual encendido, si hay foco y entrada la ranura se
  guarda como `auto`: lo medido manda.
- Los valores `bridge`, `signal` y `day` de `source` **nunca se persisten**;
  solo existen en la salida. En disco solo hay `auto` y `manual`.
- Un modo desconocido se ignora en silencio en vez de fallar.
- Los dos sesgos de precisión se compensan (leer sin tocar resta; los 3 min de
  gracia suman): bajar solo el umbral de inactividad empeora el dato.
