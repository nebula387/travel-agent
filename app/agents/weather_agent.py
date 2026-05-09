import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.weather import get_forecast, get_best_season, format_weather_text

logger = logging.getLogger(__name__)


class WeatherAgent(BaseAgent):
    async def run(self, query: str, ctx) -> dict[str, Any]:
        try:
            weather = await get_forecast(query, days=7)
            season = await get_best_season(query)

            if not weather:
                return {"weather": None, "season": season, "error": "weather_unavailable"}

            weather_text = format_weather_text(weather)
            advice = await self._synthesize(query, weather, season)

            return {
                "weather": weather,
                "weather_text": weather_text,
                "weather_advice": advice,
                "best_season": season,
                "sources": [weather.get("source", "unknown")],
            }
        except Exception:
            logger.exception("WeatherAgent failed query=%s", query)
            return {"error": "weather_agent_error"}

    async def _synthesize(self, city: str, weather: dict, season: str | None) -> str:
        temp = weather.get("temp_c", "?")
        condition = weather.get("condition", "неизвестно")
        humidity = weather.get("humidity", "?")
        season_str = f"Лучший сезон для посещения: {season}" if season else ""

        prompt = (
            f"Погода в {city} сейчас: {temp}°C, {condition}, влажность {humidity}%.\n"
            f"{season_str}\n\n"
            "Дай практичный совет путешественнику: что взять из одежды, "
            "лучшее время визита, чего избегать. 3-4 предложения, эмодзи 🌤️."
        )
        return await self._llm(prompt)
