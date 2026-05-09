import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.search import search_travel_info

logger = logging.getLogger(__name__)


class VisaAgent(BaseAgent):
    async def run(self, query: str, ctx) -> dict[str, Any]:
        """Визовая информация: веб-поиск + Gemini-синтез."""
        try:
            passport = await ctx.read("passport_country", "Россия")

            search_query = f"виза {query} гражданам {passport} 2025 требования документы"
            results = await search_travel_info(search_query, city=query, max_results=5)

            synthesis = await self._synthesize(query, passport, results)

            return {
                "visa": {"country": query, "passport": passport},
                "visa_text": synthesis,
                "search_results": results,
                "sources": ["duckduckgo"],
            }
        except Exception:
            logger.exception("VisaAgent failed query=%s", query)
            return {"error": "visa_agent_error"}

    async def _synthesize(self, destination: str, passport: str, results: list) -> str:
        snippets = "\n".join(
            f"- {r['title']}: {r.get('snippet', '')[:150]}"
            for r in results[:4]
        )
        prompt = (
            f"Нужна ли виза гражданам {passport} для въезда в {destination}?\n\n"
            f"Данные из поиска:\n{snippets}\n\n"
            "Ответь кратко: нужна ли виза, как получить, срок, стоимость если известна. "
            "Если есть visa-on-arrival или e-visa — укажи. Используй эмодзи 🛂."
        )
        return await self._llm(prompt)

    async def research(self, destination: str, passport: str) -> dict[str, Any]:
        """Прямой вызов без ctx."""
        results = await search_travel_info(
            f"виза {destination} гражданам {passport} 2025", max_results=5
        )
        synthesis = await self._synthesize(destination, passport, results)
        return {
            "destination": destination,
            "passport": passport,
            "summary": synthesis,
            "sources": results,
        }
