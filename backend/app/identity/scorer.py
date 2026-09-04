"""
Resolución de identidad mediante Fellegi-Sunter.

Decide, para cada hallazgo, la probabilidad de que pertenezca al objetivo. Es
una pregunta distinta de la que responde cada herramienta OSINT ("¿existe esta
cuenta?"): un perfil puede existir con total certeza y no ser de la persona
investigada. Este módulo solo se ocupa de la **atribución**.

Modelo de tres estados
----------------------
Fellegi-Sunter clásico distingue acuerdo, desacuerdo y **dato ausente**. La
implementación anterior colapsaba los dos últimos: si el objetivo no había
aportado teléfono, `phone_match` valía 0.0 y el modelo cobraba -4.32 bits por un
campo que nunca se pudo observar. Con siete señales, el caso base sumaba -31.6
bits, es decir una probabilidad posterior de 6e-12 que el recorte final subía a
0.05. La distribución resultante era trimodal {0.05, 0.45, 0.95} en lugar de
continua, y el umbral de 0.70 del resolutor resultaba inalcanzable salvo por los
atajos que había justo debajo del cálculo.

Aquí cada señal declara si es **evaluable** para el par (objetivo, hallazgo)
concreto. Si no lo es, queda fuera del sumatorio y aporta exactamente 0 bits.
Con todas las señales no evaluables la probabilidad posterior es la previa, que
es lo que corresponde: sin evidencia no hay actualización bayesiana.
"""

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from thefuzz import fuzz

from app.models.target import Target

# Identifica la versión del modelo en cada breakdown persistido. Sin esto, las
# investigaciones anteriores y posteriores a un recalibrado no son comparables y
# cualquier análisis agregado mezcla dos modelos distintos.
SCORER_VERSION = "2.0.0"

# Probabilidad de coincidencia antes de observar ninguna señal.
#
# Sube de 0.02 a 0.10. El 2% correspondía a un emparejamiento contra una
# población arbitraria, pero aquí los candidatos no son arbitrarios: llegan de
# búsquedas dirigidas al identificador del objetivo (su alias, su nombre, su
# correo). Un candidato recuperado así tiene bastante más de un 2% de
# probabilidad a priori de ser la persona. Mantenerlo tan bajo obligaba a
# acumular ~6.8 bits solo para llegar al umbral de decisión, lo que descartaba
# evidencias legítimas como un dominio personal que enlaza al GitHub del sujeto.
PRIOR_MATCH_PROBABILITY = 0.10

# Los pesos de las señales muy discriminantes (correo, prueba criptográfica)
# superan los +12 bits. Como las señales no son estrictamente independientes
# entre sí -- nombre, alias y enlaces cruzados covarían -- acumular sin límite
# produce certezas artificiales. Se acota el log-verosimilitud total.
MAX_ABS_LOG_LIKELIHOOD = 20.0

# Herramientas que enumeran un identificador conocido a través de muchas
# plataformas. Sus hallazgos coinciden con ese identificador POR CONSTRUCCIÓN,
# así que la señal correspondiente no aporta información y debe declararse no
# evaluable, igual que se hace con las aristas tautológicas del grafo.
ENUMERATION_TOOLS = {
    "username": {"username_finder", "infostealer_checker"},
    "email": {
        "email_enumerator",
        "email_checker",
        "gravatar_deep",
        "breach_checker",
        "infostealer_checker",
    },
}


@dataclass
class SignalContext:
    """Todo lo que una señal necesita para decidir si aplica y en qué grado."""

    target: Target
    metadata: Dict[str, Any]
    value: str
    display_name: Optional[str]

    @property
    def source_tool(self) -> str:
        raw = str(self.metadata.get("source_tool") or "")
        return raw.removeprefix("agent:")

    @property
    def source_tools(self) -> List[str]:
        """
        Todas las herramientas que reportaron este hallazgo.

        La deduplicación conserva el hallazgo de mayor confianza, pero la
        procedencia importa entera: un perfil descubierto al enumerar el alias y
        luego reverificado por otra herramienta sigue siendo un hallazgo cuya
        coincidencia de alias está garantizada por el método de búsqueda.
        """
        raw = self.metadata.get("source_tools")
        tools = [str(t).removeprefix("agent:") for t in raw] if isinstance(raw, list) else []
        if self.source_tool and self.source_tool not in tools:
            tools.append(self.source_tool)
        return tools

    def discovered_by_enumerating(self, field: str) -> bool:
        enumerators = ENUMERATION_TOOLS.get(field, set())
        return any(tool in enumerators for tool in self.source_tools)

    def text(self, *keys: str) -> str:
        """Concatena los campos de metadata indicados que sean texto."""
        parts: List[str] = []
        for key in keys:
            raw = self.metadata.get(key)
            if isinstance(raw, str):
                parts.append(raw)
            elif isinstance(raw, list):
                parts.extend(str(x) for x in raw)
        return " ".join(p for p in parts if p)

    def emails_found(self) -> List[str]:
        found = []
        for key in ("emails", "extracted_emails", "email"):
            raw = self.metadata.get(key)
            if isinstance(raw, str):
                found.append(raw)
            elif isinstance(raw, list):
                found.extend(str(x) for x in raw)
        return [e.strip().lower() for e in found if e]

    def usernames_found(self) -> List[str]:
        found = []
        for key in ("usernames", "extracted_usernames", "username"):
            raw = self.metadata.get(key)
            if isinstance(raw, str):
                found.append(raw)
            elif isinstance(raw, list):
                found.extend(str(x) for x in raw)
        return [u.strip().lower().lstrip("@") for u in found if u]

    def linked_profiles(self) -> List[str]:
        raw = self.metadata.get("linked_profiles")
        return [str(x).lower() for x in raw] if isinstance(raw, list) else []


@dataclass(frozen=True)
class Signal:
    """
    Una señal del modelo.

    `m` = P(acuerdo | es la misma persona)
    `u` = P(acuerdo | son personas distintas)

    El poder discriminante es log2(m/u): cuanto más improbable sea la
    coincidencia por azar, más pesa cuando ocurre.
    """

    name: str
    m: float
    u: float
    description: str
    applicable: Callable[[SignalContext], bool]
    gamma: Callable[[SignalContext], float]

    @property
    def weight_agree(self) -> float:
        return math.log2(self.m / self.u)

    @property
    def weight_disagree(self) -> float:
        return math.log2((1.0 - self.m) / (1.0 - self.u))


# --- Utilidades de comparación -------------------------------------------


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


# Campos en los que una herramienta afirma explícitamente el nombre asociado a
# un perfil. Su presencia es lo que hace evaluable la señal de nombre.
ASSERTED_NAME_FIELDS = ("og_title", "name", "full_name", "google_display_name")


def _asserts_a_name(ctx: SignalContext) -> bool:
    """
    ¿La fuente afirma un nombre para este hallazgo?

    Distingue el desacuerdo de la ausencia. Un dominio personal cuyo
    `display_name` es "Portafolio personal" no está contradiciendo el nombre del
    objetivo: sencillamente no declara ninguno, y penalizarlo hundía evidencias
    fuertes como que ese mismo sitio enlace al GitHub del sujeto. `display_name`
    por sí solo no basta, porque muchas herramientas lo rellenan con el título
    de la página o con el propio alias.
    """
    return any(str(ctx.metadata.get(f) or "").strip() for f in ASSERTED_NAME_FIELDS)


def _name_corpus(ctx: SignalContext) -> str:
    """
    Campos donde razonablemente aparece el nombre de una persona.

    Deliberadamente NO incluye la biografía. La versión anterior la metía aquí y
    la comparaba con `fuzz.partial_ratio`, que busca la mejor subcadena: una bio
    larga casi siempre contiene algún fragmento parecido a un nombre común, lo
    que inflaba la señal más frecuente del sistema. La bio se explota en su
    lugar mediante la señal de afiliación y, cuando hay LLM, la semántica.
    """
    return " ".join(
        p
        for p in [
            ctx.display_name or "",
            *(str(ctx.metadata.get(f) or "") for f in ASSERTED_NAME_FIELDS),
        ]
        if p
    ).strip()


def _affiliation_corpus(ctx: SignalContext) -> str:
    return ctx.text("bio", "snippet", "institutions", "company_university", "og_description")


# --- Definición de las señales -------------------------------------------

SIGNALS: Tuple[Signal, ...] = (
    Signal(
        name="name_match",
        # m baja de 0.92 a 0.78. En OSINT, buena parte de los perfiles que SÍ
        # son de la persona no muestran su nombre real: usan el alias, un
        # apodo, iniciales o el título genérico de una página ("Portafolio
        # personal"). Afirmar que el 92% de las coincidencias verdaderas
        # exhiben el nombre convertía esa ausencia en una penalización de -3.6
        # bits que hundía hallazgos legítimos.
        #
        # u sube de 0.005 a 0.02: con comparación difusa sobre nombres hispanos,
        # donde los apellidos se repiten mucho, la coincidencia parcial por azar
        # es más frecuente de lo que suponía el valor anterior.
        m=0.78,
        u=0.02,
        description="Coincidencia del nombre con el nombre mostrado del perfil.",
        applicable=lambda c: bool(c.target.full_name and _asserts_a_name(c)),
        gamma=lambda c: _gamma_name(c),
    ),
    Signal(
        name="email_match",
        m=0.98,
        u=0.0005,
        description="El perfil declara el correo del objetivo.",
        applicable=lambda c: bool(
            c.target.email
            and not c.discovered_by_enumerating("email")
            and (c.emails_found() or "@" in c.value)
        ),
        gamma=lambda c: 1.0
        if (c.target.email or "").strip().lower() in c.emails_found()
        or (c.target.email or "").strip().lower() in c.value.lower()
        else 0.0,
    ),
    Signal(
        name="university_match",
        # u sube de 0.04 a 0.12: el público objetivo son estudiantes de unas
        # pocas universidades, así que dos personas distintas del mismo centro
        # coinciden en afiliación con mucha frecuencia. Es una señal de apoyo,
        # no de identificación.
        m=0.85,
        u=0.12,
        description="La afiliación institucional del objetivo aparece en el perfil.",
        applicable=lambda c: bool(c.target.university and _affiliation_corpus(c)),
        gamma=lambda c: _gamma_affiliation(c),
    ),
    Signal(
        name="username_match",
        # m baja de 0.88 a 0.60. Reutilizar el mismo alias en todas partes es
        # precisamente el mal hábito que esta plataforma enseña a evitar: dar
        # por hecho que el 88% de las cuentas de una persona comparten alias
        # penalizaba con -3.0 bits los casos en que no lo hacen, que son
        # justamente los que descubre la correlación por avatar o por correo.
        m=0.60,
        u=0.008,
        description="El alias del objetivo coincide con el del perfil.",
        # No evaluable si el hallazgo procede de enumerar ese mismo alias (la
        # coincidencia estaría garantizada por el método de búsqueda) ni si el
        # perfil no declara ningún alias que comparar.
        applicable=lambda c: bool(
            c.target.username
            and c.usernames_found()
            and not c.discovered_by_enumerating("username")
        ),
        gamma=lambda c: _gamma_username(c),
    ),
    Signal(
        name="phone_match",
        m=0.95,
        u=0.0002,
        description="El teléfono del objetivo aparece en el perfil.",
        applicable=lambda c: bool(c.target.phone and (c.metadata.get("phones") or _digits(c.value))),
        gamma=lambda c: _gamma_phone(c),
    ),
    Signal(
        name="cross_link",
        # Antes esta señal valía 1.0 con que el perfil enlazara a cualquier
        # sitio, lo cual es cierto para casi todos: con u=0.01 afirmaba que solo
        # el 1% de los perfiles ajenos enlazan a algo. Ahora exige que el enlace
        # apunte a un identificador CONOCIDO del objetivo, que es lo que
        # realmente constituye evidencia.
        m=0.80,
        # u=0.005: que un perfil ajeno enlace por azar al alias o correo
        # *concretos* del objetivo es muy improbable. Antes valía 0.02 heredado
        # de cuando la señal se activaba con cualquier enlace saliente.
        u=0.005,
        description="El perfil enlaza a otra identidad conocida del objetivo.",
        # Solo evaluable si el perfil publica enlaces salientes. Antes bastaba
        # con que trajera un alias propio, de modo que la señal se activaba en
        # casi todos los hallazgos y un perfil con enlaces cualesquiera sumaba
        # +5.3 bits sin que ninguno apuntara al objetivo.
        applicable=lambda c: bool(
            c.linked_profiles() and (c.target.username or c.target.email)
        ),
        gamma=lambda c: _gamma_cross_link(c),
    ),
    Signal(
        name="cryptographic_proof",
        m=0.999,
        u=0.00001,
        description="Identidad demostrada con firma criptográfica (Keybase).",
        # Solo evaluable si la herramienta se pronuncia. Que un perfil de
        # Instagram no traiga prueba criptográfica no es un desacuerdo.
        applicable=lambda c: "cryptographically_proven" in c.metadata,
        gamma=lambda c: 1.0 if c.metadata.get("cryptographically_proven") else 0.0,
    ),
    Signal(
        name="avatar_match",
        m=0.97,
        u=0.005,
        description="La foto de perfil coincide con la de otra cuenta ya atribuida.",
        # La calcula la pasada de enriquecimiento (identity/enrichment.py) tras
        # el hashing perceptual; aquí solo se lee.
        applicable=lambda c: "avatar_similarity" in c.metadata,
        gamma=lambda c: _clamp01(float(c.metadata.get("avatar_similarity") or 0.0)),
    ),
    Signal(
        name="semantic_bio_match",
        # Señal de apoyo: capta equivalencias que el cotejo léxico no ve
        # ("UNMSM" contra "Universidad Nacional Mayor de San Marcos"), pero dos
        # estudiantes de la misma carrera describen intereses parecidos, de ahí
        # una u alta.
        m=0.75,
        u=0.15,
        description="La biografía describe semánticamente al mismo perfil.",
        applicable=lambda c: "semantic_similarity" in c.metadata,
        gamma=lambda c: _clamp01(float(c.metadata.get("semantic_similarity") or 0.0)),
    ),
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# Similitud por debajo de la cual dos nombres no se consideran el mismo. El
# grado de acuerdo se reescala sobre este umbral en vez de usar la similitud en
# bruto, porque la interpolación del peso cruza a positivo ya en gamma≈0.29: con
# la similitud sin reescalar, compartir un solo apellido (~0.63) contaba como
# evidencia a favor y bastaba, junto a la universidad, para atribuir a un
# familiar o a un homónimo el perfil del objetivo.
NAME_AGREEMENT_FLOOR = 0.75


def _gamma_name(ctx: SignalContext) -> float:
    """
    Grado de acuerdo continuo del nombre.

    `token_set_ratio` en lugar de `partial_ratio`: compara conjuntos de palabras,
    de modo que tolera el orden y los nombres abreviados ("Carlos E. Mendoza"
    frente a "Carlos Eduardo Mendoza") sin premiar cualquier subcadena parecida.

    Medido sobre nombres hispanos de tres componentes: idéntico 1.00, abreviado
    0.93, solo el apellido en común 0.63, sin relación 0.38. El reescalado deja
    fuera los dos últimos, que es justo donde viven los homónimos y los
    familiares.
    """
    target_name = (ctx.target.full_name or "").strip().lower()
    corpus = _name_corpus(ctx).lower()
    if not target_name or not corpus:
        return 0.0

    ratio = fuzz.token_set_ratio(target_name, corpus) / 100.0
    if ratio < NAME_AGREEMENT_FLOOR:
        return 0.0
    return round((ratio - NAME_AGREEMENT_FLOOR) / (1.0 - NAME_AGREEMENT_FLOOR), 2)


def _gamma_affiliation(ctx: SignalContext) -> float:
    """
    Afiliación institucional, con tolerancia a siglas y formas abreviadas.

    La versión anterior exigía subcadena exacta, así que "Univ. Nacional de
    Tumbes" no casaba con "Universidad Nacional de Tumbes".
    """
    uni = (ctx.target.university or "").strip().lower()
    corpus = _affiliation_corpus(ctx).lower()
    if not uni or not corpus:
        return 0.0

    if uni in corpus:
        return 1.0

    # Siglas formadas por las iniciales de las palabras significativas.
    words = [w for w in re.split(r"\W+", uni) if len(w) > 2]
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words)
        if len(acronym) >= 3 and re.search(rf"\b{re.escape(acronym)}\b", corpus):
            return 1.0

    ratio = fuzz.token_set_ratio(uni, corpus) / 100.0
    return round(ratio, 2) if ratio >= 0.75 else 0.0


def _gamma_username(ctx: SignalContext) -> float:
    """
    Solo cuenta el alias que el perfil DECLARA en sus metadatos.

    Deliberadamente no se acepta que el alias aparezca en la URL. En este
    sistema casi todas las URLs se alcanzan buscando ese mismo alias, así que
    encontrarlo dentro de ellas es una consecuencia del método de búsqueda y no
    una observación independiente. Aceptarlo hacía que cuentas cualesquiera de
    la cola larga (`xboxgamertag.com/search/<alias>`, `forum.arduino.cc/u/<alias>`)
    alcanzaran una atribución del 99%.
    """
    user = (ctx.target.username or "").strip().lower()
    if not user:
        return 0.0
    return 1.0 if user in ctx.usernames_found() else 0.0


def _gamma_phone(ctx: SignalContext) -> float:
    """
    Coincidencia telefónica tolerante al prefijo internacional.

    El objetivo suele escribir su número en formato E.164 (+51987654321)
    mientras que los perfiles lo publican en formato nacional (987654321). El
    cotejo se hace por los últimos 8 dígitos, que es lo que identifica la línea.
    """
    target_phone = _digits(ctx.target.phone or "")
    if not target_phone:
        return 0.0

    raw_phones = ctx.metadata.get("phones")
    candidates = [_digits(str(p)) for p in raw_phones] if isinstance(raw_phones, list) else []
    candidates.append(_digits(ctx.value))

    if target_phone in candidates:
        return 1.0

    tail = target_phone[-8:]
    if len(tail) >= 8 and any(tail in c for c in candidates if c):
        return 1.0
    return 0.0


def _gamma_cross_link(ctx: SignalContext) -> float:
    """1.0 solo si un enlace o alias del perfil apunta a algo conocido del objetivo."""
    user = (ctx.target.username or "").strip().lower()
    email = (ctx.target.email or "").strip().lower()

    haystack = " ".join(ctx.linked_profiles())
    if user and (user in haystack or user in ctx.usernames_found()):
        return 1.0
    if email and email in haystack:
        return 1.0
    return 0.0


# --- Cálculo --------------------------------------------------------------


def compute_identity_score(
    display_name: str | None,
    value: str,
    metadata: Dict[str, Any],
    target: Target,
) -> Tuple[float, Dict[str, Any]]:
    """
    Devuelve (probabilidad_posterior, desglose).

    El desglose incluye, por señal, el grado de acuerdo, su peso en bits y si
    era evaluable, de modo que la interfaz pueda explicar la decisión y un
    análisis posterior pueda reproducirla.
    """
    ctx = SignalContext(
        target=target,
        metadata=metadata or {},
        value=value or "",
        display_name=display_name,
    )

    total_weight = 0.0
    evaluated = 0
    breakdown: Dict[str, Any] = {}

    for signal in SIGNALS:
        try:
            is_applicable = bool(signal.applicable(ctx))
        except Exception:
            # Los metadatos son heterogéneos: una señal mal alimentada no debe
            # tumbar la puntuación del hallazgo completo.
            is_applicable = False

        breakdown[f"{signal.name}_applicable"] = is_applicable

        if not is_applicable:
            # Ausencia de dato: contribución nula, no penalización.
            breakdown[signal.name] = 0.0
            breakdown[f"{signal.name}_weight"] = 0.0
            continue

        try:
            gamma = _clamp01(float(signal.gamma(ctx)))
        except Exception:
            gamma = 0.0

        weight = signal.weight_disagree + gamma * (signal.weight_agree - signal.weight_disagree)
        total_weight += weight
        evaluated += 1

        breakdown[signal.name] = round(gamma, 2)
        breakdown[f"{signal.name}_weight"] = round(weight, 2)

    capped_weight = max(-MAX_ABS_LOG_LIKELIHOOD, min(MAX_ABS_LOG_LIKELIHOOD, total_weight))

    prior_odds = PRIOR_MATCH_PROBABILITY / (1.0 - PRIOR_MATCH_PROBABILITY)
    posterior_odds = prior_odds * (2.0**capped_weight)
    posterior = posterior_odds / (1.0 + posterior_odds)

    breakdown["log_likelihood_ratio"] = round(total_weight, 2)
    breakdown["signals_evaluated"] = evaluated
    breakdown["scorer_version"] = SCORER_VERSION

    # Ya no hay atajos del tipo `max(posterior, 0.45)`. Existían para compensar
    # la penalización del caso base; con el modelo de tres estados sobran, y
    # eran justamente lo que colapsaba la distribución en tres valores fijos.
    return round(min(max(posterior, 0.01), 0.99), 3), breakdown
