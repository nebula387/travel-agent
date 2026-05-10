import logging
from typing import Any

import google.generativeai as genai

from app.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты бюджетный travel-советник для русскоязычных путешественников. "
    "Отвечай ТОЛЬКО на русском языке. "
    "Давай конкретные цифры, цены в USD и рублях, ссылки на ресурсы. "
    "Стиль: дружелюбный, без лишних слов, с эмодзи. "
    "Фокус: бюджетные маршруты, номадизм, Юго-Восточная Азия, Европа, Латинская Америка."
)


class BaseAgent:
    """Базовый агент с Gemini 1.5 Flash + Groq fallback."""

    async def _llm(self, prompt: str, system: str | None = None) -> str:
        full_system = system or _SYSTEM_PROMPT
        full_prompt = f"{full_system}\n\n{prompt}"

        # Primary: Gemini 1.5 Flash
        if settings.gemini_api_key:
            try:
                genai.configure(api_key=settings.gemini_api_key)
                model = genai.GenerativeModel("gemini-2.0-flash")
                response = await model.generate_content_async(full_prompt)
                return response.text.strip()
            except Exception:
                logger.exception("Gemini failed, trying Groq fallback")

        # Fallback: Groq via httpx (groq SDK incompatible with httpx>=0.28)
        if settings.groq_api_key:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        json={
                            "model": "llama-3.1-70b-versatile",
                            "messages": [
                                {"role": "system", "content": full_system},
                                {"role": "user", "content": prompt},
                            ],
                            "max_tokens": 1024,
                        },
                    )
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                logger.exception("Groq fallback also failed")

        return "⚠️ LLM недоступен, попробуй позже."

    async def run(self, query: str, ctx: Any) -> dict[str, Any]:
        raise NotImplementedError
