import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional
import litellm
from app.core.config import settings

# Esperas entre reintentos de una llamada al LLM que falló por un motivo pasajero.
#
# Un 503 de Gemini ("This model is currently experiencing high demand") suele
# durar segundos. Sin reintentar, un pico de demanda en el primer turno del
# agente dejaba la investigación sin ejecutar una sola herramienta.
RETRY_DELAYS_SECONDS = (2.0, 6.0, 15.0)

# Códigos que indican saturación o un fallo pasajero del proveedor, no un error
# de la petición: una clave inválida o un modelo inexistente no se arreglan
# esperando, y reintentarlos solo retrasaría el aviso.
TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}

OnRetry = Callable[[int, float, BaseException], Awaitable[None]]


def is_transient_llm_error(err: BaseException) -> bool:
    transient_types = (
        litellm.ServiceUnavailableError,
        litellm.RateLimitError,
        litellm.Timeout,
        litellm.APIConnectionError,
        litellm.InternalServerError,
    )
    return isinstance(err, transient_types) or getattr(err, "status_code", None) in TRANSIENT_STATUS


def describe_llm_error(err: BaseException) -> str:
    """
    El error en una frase legible.

    El de Gemini trae el JSON completo de la respuesta en varias líneas, y así
    llegaba tal cual a la consola de la investigación.
    """
    status = getattr(err, "status_code", None)
    if status == 503 or isinstance(err, litellm.ServiceUnavailableError):
        return "el modelo de IA está saturado (503)"
    if status == 429 or isinstance(err, litellm.RateLimitError):
        return "se alcanzó el límite de peticiones del proveedor de IA (429)"
    if isinstance(err, litellm.Timeout):
        return "el proveedor de IA no respondió a tiempo"
    text = str(err).strip()
    return text.splitlines()[0][:160] if text else type(err).__name__


async def complete_with_retries(*, on_retry: Optional[OnRetry] = None, **kwargs: Any) -> Any:
    """
    `litellm.acompletion` con reintentos ante fallos pasajeros del proveedor.

    Un error de la petición se propaga a la primera. `on_retry(intento, espera,
    error)` permite avisar a la interfaz mientras se espera, para que una pausa
    de varios segundos no parezca un cuelgue.
    """
    for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), start=1):
        try:
            return await litellm.acompletion(**kwargs)
        except Exception as err:
            if delay is None or not is_transient_llm_error(err):
                raise
            if on_retry:
                await on_retry(attempt, delay, err)
            await asyncio.sleep(delay)


class LLMClient:
    """Model-agnostic LLM interface using LiteLLM."""

    def __init__(self) -> None:
        self.enabled = settings.ai_enabled
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key

    async def generate_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        if not self.enabled or not self.model:
            return None

        try:
            response = await complete_with_retries(
                model=self.model,
                messages=messages,
                temperature=temperature,
                api_key=self.api_key,
                tools=tools,
            )
            return response.choices[0].message.content
        except Exception as err:
            # Fallback gracefully if LLM provider fails or quota exceeded
            print(f"[LLMClient Warning] LLM call failed: {describe_llm_error(err)}")
            return None


llm_client = LLMClient()
