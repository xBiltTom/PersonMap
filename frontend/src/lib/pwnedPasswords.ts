/**
 * Comprobación de contraseñas filtradas contra Pwned Passwords, por k-anonimato.
 *
 * **Esto vive en el navegador a propósito, y es la decisión de diseño central.**
 * Todo lo demás del proyecto pasa por el backend; esto no. Si la contraseña
 * viajara a nuestro servidor tendríamos que prometer que no la guardamos, y una
 * herramienta cuyo tema es la seguridad de la información no puede pedir que se
 * le crea: aquí no hace falta prometerlo porque la contraseña nunca sale de la
 * pestaña. Verificado el 2026-09-05: la API responde
 * `Access-Control-Allow-Origin: *`, así que el `fetch` sale directo del
 * navegador a Cloudflare sin tocar `:8000`.
 *
 * **Cómo funciona el k-anonimato.** Se calcula el SHA-1 de la contraseña y se
 * envían **solo los 5 primeros caracteres hexadecimales** del hash. El servicio
 * devuelve *todos* los hashes que empiezan por ese prefijo —medido, entre 1.900
 * y 2.500 sufijos— y la comparación se hace localmente. El servidor sabe que
 * alguien preguntó por un prefijo compartido por miles de contraseñas distintas,
 * y no puede saber cuál. Ni siquiera recibe el hash completo.
 *
 * Fuente: Have I Been Pwned - Pwned Passwords (Troy Hunt), API v3 pública,
 * gratuita y sin clave. Registrada en docs/OSINT_SOURCES.md. Nótese que la API
 * de *brechas* de HIBP sí es de pago y está descartada; esta es otra.
 *
 * **Por qué no se usa el paquete npm `hibp`.** La regla del proyecto es no
 * reinventar la rueda, pero aquí la rueda son 40 líneas y la propiedad que hay
 * que defender ante un tribunal es exactamente "solo salen 5 caracteres".
 * Delegar eso en una dependencia transitiva haría la afirmación no auditable de
 * un vistazo. El protocolo, que es la parte que no se improvisa, es el de HIBP.
 */

export const RANGE_ENDPOINT = "https://api.pwnedpasswords.com/range/";

/** Los caracteres del hash que salen del navegador. Ni uno más. */
export const PREFIX_LENGTH = 5;

export interface PwnedResult {
  /** Veces que la contraseña aparece en las filtraciones. 0 = no aparece. */
  count: number;
  /** Lo único que se envió. Se expone para poder enseñarlo en pantalla. */
  prefix: string;
  /** Sufijos recibidos: el tamaño del anonimato conseguido. */
  candidates: number;
}

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
}

/**
 * `crypto.subtle` solo existe en contextos seguros (HTTPS, o localhost). En
 * desarrollo va; servido por HTTP plano en una red, no, y conviene decirlo en
 * lugar de reventar con un `undefined`.
 */
export function cryptoAvailable(): boolean {
  return typeof crypto !== "undefined" && typeof crypto.subtle !== "undefined";
}

/**
 * SHA-1 porque es lo que indexa Pwned Passwords, no porque sea adecuado para
 * almacenar contraseñas: aquí no se almacena nada, se consulta un índice ajeno.
 */
async function sha1Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  return toHex(await crypto.subtle.digest("SHA-1", bytes));
}

/**
 * Busca el sufijo entre los devueltos.
 *
 * **La trampa del relleno.** Con `Add-Padding` el servicio inyecta sufijos
 * falsos —medido: entre 112 y 157 por consulta— y todos vienen con `count` 0.
 * Un cliente que solo comprobara "¿está mi sufijo en la lista?" y no leyera el
 * contador podría dar por filtrada una contraseña por haber coincidido con
 * relleno inventado. Por eso lo que se devuelve es el contador, y 0 significa
 * exactamente lo mismo que no estar: no filtrada.
 */
export function parseRange(body: string, suffix: string): number {
  for (const line of body.split("\n")) {
    const [candidate, countRaw] = line.trim().split(":");
    if (candidate !== suffix) continue;
    const count = Number.parseInt(countRaw ?? "", 10);
    return Number.isFinite(count) ? count : 0;
  }
  return 0;
}

export async function checkPassword(password: string): Promise<PwnedResult> {
  if (!cryptoAvailable()) {
    throw new Error(
      "El navegador no expone Web Crypto. Hace falta HTTPS o localhost."
    );
  }

  const hash = await sha1Hex(password);
  const prefix = hash.slice(0, PREFIX_LENGTH);
  const suffix = hash.slice(PREFIX_LENGTH);

  // `Add-Padding` rellena la respuesta con sufijos falsos para que su tamaño no
  // delate cuántas coincidencias reales hay. Verificado el 2026-09-05: la API
  // responde al preflight con `Access-Control-Allow-Headers: Add-Padding`, así
  // que la cabecera personalizada no rompe el CORS.
  const resp = await fetch(RANGE_ENDPOINT + prefix, {
    headers: { "Add-Padding": "true" },
  });

  if (!resp.ok) {
    throw new Error(`Pwned Passwords respondió ${resp.status}.`);
  }

  const body = await resp.text();

  return {
    count: parseRange(body, suffix),
    prefix,
    candidates: body.trim().split("\n").filter(Boolean).length,
  };
}

/** Tramos para presentar el resultado. La cifra sola no dice qué hacer. */
export interface ExposureVerdict {
  titulo: string;
  texto: string;
  accion: string;
  tone: string;
  badge: string;
}

export function verdictFor(count: number): ExposureVerdict {
  if (count === 0) {
    return {
      titulo: "No aparece en las filtraciones conocidas",
      texto:
        "Esta contraseña no figura en los más de 900 millones de credenciales " +
        "recopiladas de brechas públicas, así que no está en los diccionarios " +
        "que se usan para probar accesos en masa.",
      accion:
        "No aparecer no la vuelve fuerte: una contraseña corta y predecible " +
        "puede seguir cayendo aunque nadie la haya filtrado todavía.",
      tone: "text-emerald-300",
      badge: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
    };
  }

  if (count < 100) {
    return {
      titulo: "Aparece en filtraciones",
      texto:
        "Está en las recopilaciones públicas de credenciales robadas. Aunque " +
        "aparezca pocas veces, ya forma parte de las listas con las que se " +
        "prueban accesos automáticamente.",
      accion: "Cámbiala en todos los sitios donde la hayas reutilizado.",
      tone: "text-amber-300",
      badge: "bg-amber-500/20 text-amber-300 border-amber-500/30",
    };
  }

  return {
    titulo: "Comprometida y muy común",
    texto:
      "Aparece miles de veces, lo que significa que está en la cabecera de los " +
      "diccionarios de ataque. Un intento de acceso por fuerza bruta la prueba " +
      "en los primeros segundos.",
    accion:
      "Cámbiala ya en todas las cuentas donde la uses, empezando por el correo, " +
      "que es el que permite recuperar las demás.",
    tone: "text-rose-300",
    badge: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  };
}
