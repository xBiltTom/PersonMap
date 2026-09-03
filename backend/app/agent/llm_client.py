from typing import Any, Dict, List, Optional
import litellm
from app.core.config import settings


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
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=temperature,
                api_key=self.api_key,
                tools=tools,
            )
            return response.choices[0].message.content
        except Exception as err:
            # Fallback gracefully if LLM provider fails or quota exceeded
            print(f"[LLMClient Warning] LLM call failed: {err}")
            return None


llm_client = LLMClient()
