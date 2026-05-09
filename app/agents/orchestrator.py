import asyncio
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.memory.context import SharedContext

logger = logging.getLogger(__name__)

# Intent → keywords (fast pre-filter before Gemini)
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "visa":     ["виза", "визов", "документ", "паспорт", "въезд", "разрешени"],
    "weather":  ["погода", "климат", "температур", "сезон", "дождь", "жарко", "холодно"],
    "flights":  ["билет", "рейс", "перелёт", "авиа", "лететь", "самолёт", "аэропорт"],
    "budget":   ["бюджет", "стоимость", "цена", "деньги", "стоит", "дорого", "дёшево", "расход"],
    "worldtrip": ["кругосветк", "маршрут мечты", "worldtrip", "путешествие по миру"],
    "maps":     ["карт", "район", "жильё", "хостел", "коворкинг", "как добрать", "маршрут"],
}


class Orchestrator(BaseAgent):
    """Классифицирует запрос → запускает агентов параллельно → синтезирует ответ через Gemini."""

    async def run(self, query: str, user_id: int) -> dict[str, Any]:
        ctx = SharedContext(user_id)
        await ctx.write("last_query", query)

        intents = await self.classify_intent(query)
        logger.info("user=%s intents=%s query=%r", user_id, intents, query[:80])

        agent_tasks = self._build_tasks(intents, query, ctx)
        if not agent_tasks:
            agent_tasks = [self._fallback_task(query, ctx)]

        raw_results = await asyncio.gather(*agent_tasks, return_exceptions=True)

        merged: dict[str, Any] = {"intents": intents}
        for r in raw_results:
            if isinstance(r, Exception):
                logger.warning("Agent returned exception: %s", r)
            elif isinstance(r, dict):
                merged.update(r)

        text = await self.synthesize_results(query, merged)
        return {"text": text, "data": merged}

    # ── Intent classification ────────────────────────────────────────────────

    async def classify_intent(self, query: str) -> list[str]:
        """Fast keyword pre-filter, Gemini only if ambiguous."""
        q = query.lower()
        matched = [
            intent for intent, kws in _INTENT_KEYWORDS.items()
            if any(kw in q for kw in kws)
        ]
        if matched:
            return matched

        # Gemini disambiguation for free-form queries
        prompt = (
            "Определи намерения пользователя из запроса. "
            "Выбери ТОЛЬКО подходящие из списка: visa, weather, flights, budget, maps, worldtrip, general.\n"
            "Ответь JSON-массивом, например: [\"weather\", \"budget\"]\n\n"
            f"Запрос: {query}"
        )
        try:
            raw = await self._llm(prompt, system="Ты классификатор намерений. Отвечай только JSON.")
            # Extract JSON array from response
            start, end = raw.find("["), raw.rfind("]")
            if start != -1 and end != -1:
                intents = json.loads(raw[start:end + 1])
                valid = {"visa", "weather", "flights", "budget", "maps", "worldtrip", "general"}
                return [i for i in intents if i in valid] or ["general"]
        except Exception:
            logger.exception("Intent classification failed")
        return ["general"]

    # ── Agent dispatch ───────────────────────────────────────────────────────

    def _build_tasks(self, intents: list[str], query: str, ctx: SharedContext) -> list:
        tasks = []
        if "visa" in intents:
            from app.agents.visa_agent import VisaAgent
            tasks.append(VisaAgent().run(query, ctx))
        if "weather" in intents:
            from app.agents.weather_agent import WeatherAgent
            tasks.append(WeatherAgent().run(query, ctx))
        if "flights" in intents:
            from app.agents.flight_agent import FlightAgent
            tasks.append(FlightAgent().run(query, ctx))
        if "budget" in intents:
            from app.agents.budget_agent import BudgetAgent
            tasks.append(BudgetAgent().run(query, ctx))
        if "maps" in intents or "general" in intents:
            from app.agents.maps_agent import MapsAgent
            tasks.append(MapsAgent().run(query, ctx))
        if "worldtrip" in intents:
            from app.agents.worldtrip_agent import WorldTripAgent
            tasks.append(WorldTripAgent().run(query, ctx))
        return tasks

    async def _fallback_task(self, query: str, ctx: SharedContext) -> dict[str, Any]:
        from app.agents.maps_agent import MapsAgent
        return await MapsAgent().run(query, ctx)

    # ── Result synthesis ─────────────────────────────────────────────────────

    async def synthesize_results(self, query: str, data: dict[str, Any]) -> str:
        """Gemini синтезирует все данные агентов в связный ответ для Telegram."""
        # Build a compact data summary for the prompt
        summary_parts: list[str] = []

        if data.get("budget"):
            b = data["budget"]
            summary_parts.append(
                f"Стоимость жизни: {b.get('total_budget', '?')} USD/мес"
            )
        if data.get("budget_text"):
            summary_parts.append(data["budget_text"])
        if data.get("weather_text"):
            summary_parts.append(f"Погода: {data['weather_text']}")
        if data.get("best_season"):
            summary_parts.append(f"Лучший сезон: {data['best_season']}")
        if data.get("flights_text"):
            summary_parts.append(f"Авиабилеты: {data['flights_text']}")
        if data.get("visa"):
            v = data["visa"]
            summary_parts.append(
                f"Виза: {v.get('country', '')} для паспорта {v.get('passport', '')}"
            )
        if data.get("search_results"):
            snippets = [
                f"- {r.get('title', '')}: {r.get('snippet', '')[:100]}"
                for r in data["search_results"][:3]
            ]
            summary_parts.append("Актуальная информация:\n" + "\n".join(snippets))
        if data.get("worldtrip"):
            summary_parts.append(f"Кругосветка: {data['worldtrip']}")
        if data.get("geo"):
            g = data["geo"]
            summary_parts.append(f"Координаты: {g.get('lat')}, {g.get('lng')}")
        if data.get("airport_routes"):
            summary_parts.append(f"Маршруты из аэропорта: {data['airport_routes']}")

        if not summary_parts:
            summary_parts.append("Данные не найдены.")

        data_block = "\n".join(summary_parts)
        prompt = (
            f"Запрос пользователя: «{query}»\n\n"
            f"Данные от агентов:\n{data_block}\n\n"
            "Напиши полезный ответ для Telegram в 3-7 предложениях. "
            "Используй эмодзи, конкретные цифры. "
            "Если есть ссылки — добавь их. "
            "Не повторяй данные дословно — дай советы на их основе."
        )
        return await self._llm(prompt)
