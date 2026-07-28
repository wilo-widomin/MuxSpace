// Triángulo de plegar/desplegar de las persianas del lateral. Caja de tamaño
// fijo para que los cuatro queden del mismo tamaño y a la misma altura.
export function SectionCaret({ open }) {
  return (
    <span className="flex h-[21px] w-[21px] shrink-0 items-center justify-center text-[21px] leading-none">
      {open ? '▾' : '▸'}
    </span>
  )
}
