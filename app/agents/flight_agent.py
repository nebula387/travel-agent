import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.flights import search_flights, format_flights_text, get_flight_link, google_flights_link

logger = logging.getLogger(__name__)


class FlightAgent(BaseAgent):
    async def run(self, query: str, ctx) -> dict[str, Any]:
        """query: 'Москва Бангкок' или 'MOW BKK 2025-03-15'"""
        try:
            parts = query.strip().split()
            origin = parts[0] if len(parts) > 0 else "MOW"
            destination = parts[1] if len(parts) > 1 else ""
            date = parts[2] if len(parts) > 2 else None

            if not destination:
                return {"error": "no_destination"}

            result = await search_flights(origin, destination, date)
            flights_text = format_flights_text(result)
            deeplink = get_flight_link(origin, destination, date)
            fallback_link = google_flights_link(origin, destination)

            advice = await self._synthesize(origin, destination, date, result, deeplink, fallback_link)

            return {
                "flights": result,
                "flights_text": flights_text,
                "flight_deeplink": deeplink,
                "flight_fallback": fallback_link,
                "flights_advice": advice,
                "sources": ["travelpayouts"],
            }
        except Exception:
            logger.exception("FlightAgent failed query=%s", query)
            return {"error": "flight_agent_error"}

    async def _synthesize(
        self,
        origin: str,
        destination: str,
        date: str | None,
        result: dict,
        deeplink: str,
        fallback: str,
    ) -> str:
        prices = result.get("prices", [])
        if prices:
            cheapest = prices[0]
            price_info = (
                f"Самый дешёвый: {cheapest.get('price', '?')} {cheapest.get('currency', 'USD')} "
                f"({cheapest.get('airline', '?')}, {cheapest.get('transfers', 0)} пересадок)"
            )
        else:
            price_info = "Точные цены недоступны (данные кэша устарели)."

        date_str = date or "ближайшие даты"
        prompt = (
            f"Рейс: {origin} → {destination}, дата: {date_str}\n"
            f"{price_info}\n"
            f"Ссылка на билеты: {deeplink}\n"
            f"Альтернатива: {fallback}\n\n"
            "Дай совет: когда лучше лететь, стоит ли брать прямой или с пересадкой, "
            "лайфхаки по поиску дешёвых билетов на это направление. 3-4 предложения, эмодзи ✈️."
        )
        return await self._llm(prompt)

    async def search(self, origin: str, destination: str, date: str | None = None) -> dict[str, Any]:
        """Прямой вызов без ctx."""
        result = await search_flights(origin, destination, date)
        return {
            "flights": result,
            "text": format_flights_text(result),
            "deeplink": get_flight_link(origin, destination, date),
            "fallback": google_flights_link(origin, destination),
        }
