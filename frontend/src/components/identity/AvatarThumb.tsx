"use client";

/**
 * Miniatura del avatar de un hallazgo.
 *
 * Existe como componente propio por dos motivos: lo usan la tabla de hallazgos y
 * el panel de evidencia, y concentra en un solo sitio la decisión de usar `<img>`
 * en lugar de `next/image`.
 *
 * **Por qué `<img>`.** `next/image` optimiza descargando la imagen *desde
 * nuestro servidor*, y estas URLs apuntan a hosts arbitrarios descubiertos en
 * tiempo de ejecución por el pivoteo pasivo. Usarlo convertiría al frontend en
 * un proxy de peticiones salientes hacia donde diga un tercero, que en un
 * proyecto cuyo tema es la seguridad de la información no es defendible. Los
 * docs de Next piden acotar `remotePatterns` "lo máximo posible" y aquí no hay
 * lista posible: el conjunto de hosts es abierto por diseño. Además son
 * miniaturas de 28-48 px, donde la optimización no aporta nada.
 */

interface Props {
  url: string;
  /** Bits de diferencia con otra cuenta. `undefined` si no hubo correlación. */
  distance?: number;
  source?: string;
  size?: "sm" | "lg";
}

export function AvatarThumb({ url, distance, source, size = "sm" }: Props) {
  const correlated = typeof distance === "number";
  const box = size === "lg" ? "w-12 h-12" : "w-7 h-7";

  const title = correlated
    ? `Avatar correlacionado: ${distance} bit${distance === 1 ? "" : "s"} de ` +
      `diferencia con otra cuenta${distance === 0 ? " (imagen idéntica)" : ""}.`
    : `Avatar${source ? ` de ${source}` : ""}`;

  return (
    // eslint-disable-next-line @next/next/no-img-element -- ver el docstring.
    <img
      src={url}
      alt=""
      loading="lazy"
      title={title}
      className={`${box} rounded object-cover shrink-0 border ${
        correlated
          ? "border-amber-400/70 ring-1 ring-amber-400/30"
          : "border-[#233044]"
      }`}
    />
  );
}
