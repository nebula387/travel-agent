import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.maps import geocode, search_places, airport_to_city_routes, build_static_map_url

logger = logging.getLogger(__name__)


class MapsAgent(BaseAgent):
    async def run(self, query: str, ctx) -> dict[str, Any]:
        try:
            geo = await geocode(query)
            places: list = []
            map_url = None
            airport = None

            if geo:
                places = await search_places(
                    query="coworking cafe hostel restaurant market",
                    location=query,
                    radius=2000,
                )
                map_url = build_static_map_url([{"lat": geo["lat"], "lng": geo["lng"]}])
                airport = await airport_to_city_routes(query)

            maps_text = await self._synthesize(query, geo, places, airport)

            return {
                "geo": geo,
                "places": places[:5],
                "map_url": map_url,
                "airport_routes": airport,
                "maps_text": maps_text,
                "sources": ["google_maps"],
            }
        except Exception:
            logger.exception("MapsAgent failed query=%s", query)
            return {"error": "maps_agent_error"}

    async def _synthesize(
        self,
        city: str,
        geo: dict | None,
        places: list,
        airport_routes: Any,
    ) -> str:
        coords = f"{geo['lat']:.4f}, {geo['lng']:.4f}" if geo else "не найдены"
        place_list = "\n".join(
            f"- {p.get('name', '?')} ({p.get('type', '')})"
            for p in places[:5]
        ) or "нет данных"
        airport_info = str(airport_routes) if airport_routes else "нет данных"

        prompt = (
            f"Город: {city} (координаты: {coords})\n"
            f"Интересные места рядом:\n{place_list}\n"
            f"Маршруты из аэропорта: {airport_info}\n\n"
            "Дай краткий совет номаду: лучший район для жилья, как добраться из аэропорта, "
            "что посетить. 3-5 предложений, эмодзи 🗺️."
        )
        return await self._llm(prompt)

    async def get_arrival_routes(self, city: str) -> dict[str, Any]:
        geo = await geocode(city)
        airport = await airport_to_city_routes(city) if geo else None
        return {"city": city, "geo": geo, "airport_routes": airport}

    async def find_housing_areas(self, city: str) -> list[dict]:
        places = await search_places(
            query="hostel guesthouse coworking",
            location=city,
            radius=3000,
        )
        return places[:8]

    async def build_map_for_telegram(self, city: str) -> str | None:
        geo = await geocode(city)
        if not geo:
            return None
        return build_static_map_url([{"lat": geo["lat"], "lng": geo["lng"]}])
