"""Google Maps tools — все вызовы sync googlemaps оборачиваем в executor."""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import googlemaps

from app.config import settings

logger = logging.getLogger(__name__)

# ── Client ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _client() -> googlemaps.Client | None:
    key = settings.google_maps_api_key
    if not key or key == "placeholder":
        logger.warning("GOOGLE_MAPS_API_KEY not set")
        return None
    return googlemaps.Client(key=key, timeout=10)


async def _run(fn, *args, **kwargs) -> Any:
    """Run a synchronous googlemaps call in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# ── Public functions ───────────────────────────────────────────────────────────

async def geocode(address: str) -> dict[str, Any] | None:
    """Вернуть {lat, lng, formatted_address} или None."""
    gmaps = _client()
    if not gmaps:
        return None
    try:
        results = await _run(gmaps.geocode, address, language="ru")
        if not results:
            return None
        r = results[0]
        loc = r["geometry"]["location"]
        return {
            "lat": loc["lat"],
            "lng": loc["lng"],
            "formatted_address": r.get("formatted_address", address),
        }
    except Exception:
        logger.exception("geocode failed address=%s", address)
        return None


async def get_directions(
    origin: str,
    destination: str,
    mode: str = "transit",
) -> dict[str, Any] | None:
    """
    Маршрут от origin до destination.
    mode: transit | driving | walking | bicycling
    Возвращает {distance, duration, steps, start_address, end_address}.
    """
    gmaps = _client()
    if not gmaps:
        return None
    try:
        results = await _run(
            gmaps.directions,
            origin,
            destination,
            mode=mode,
            language="ru",
            alternatives=False,
        )
        if not results:
            return None
        leg = results[0]["legs"][0]
        steps = []
        for step in leg["steps"][:12]:
            # Strip HTML tags from instructions
            import re
            instruction = re.sub(r"<[^>]+>", " ", step.get("html_instructions", "")).strip()
            steps.append({
                "instruction": instruction,
                "distance": step["distance"]["text"],
                "duration": step["duration"]["text"],
                "mode": step.get("travel_mode", mode).lower(),
            })
        return {
            "distance": leg["distance"]["text"],
            "duration": leg["duration"]["text"],
            "duration_seconds": leg["duration"]["value"],
            "start_address": leg["start_address"],
            "end_address": leg["end_address"],
            "mode": mode,
            "steps": steps,
        }
    except Exception:
        logger.exception("get_directions failed %s→%s mode=%s", origin, destination, mode)
        return None


async def search_places(
    query: str,
    location: str,
    radius: int = 1000,
    place_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Найти места рядом с location по запросу query.
    Возвращает список {name, address, rating, lat, lng, place_id}.
    """
    gmaps = _client()
    if not gmaps:
        return []
    try:
        geo = await geocode(location)
        if not geo:
            return []
        latlng = (geo["lat"], geo["lng"])

        kwargs: dict[str, Any] = {
            "location": latlng,
            "radius": radius,
            "language": "ru",
        }
        if place_type:
            kwargs["type"] = place_type
        if query:
            kwargs["keyword"] = query

        result = await _run(gmaps.places_nearby, **kwargs)
        places = []
        for p in result.get("results", [])[:8]:
            loc = p["geometry"]["location"]
            places.append({
                "name": p.get("name", ""),
                "address": p.get("vicinity", ""),
                "rating": p.get("rating"),
                "user_ratings_total": p.get("user_ratings_total", 0),
                "lat": loc["lat"],
                "lng": loc["lng"],
                "place_id": p.get("place_id", ""),
                "types": p.get("types", [])[:3],
                "open_now": p.get("opening_hours", {}).get("open_now"),
            })
        return places
    except Exception:
        logger.exception("search_places failed query=%s location=%s", query, location)
        return []


async def airport_to_city_routes(city: str) -> dict[str, Any] | None:
    """
    Маршруты из аэропорта города в центр города (transit + driving).
    """
    airport_query = f"аэропорт {city}"
    city_center = f"центр города {city}"
    try:
        transit = await get_directions(airport_query, city_center, mode="transit")
        driving = await get_directions(airport_query, city_center, mode="driving")
        if not transit and not driving:
            return None
        return {
            "city": city,
            "airport": airport_query,
            "transit": transit,
            "driving": driving,
        }
    except Exception:
        logger.exception("airport_to_city_routes failed city=%s", city)
        return None


def build_static_map_url(
    waypoints: list[dict[str, float]],
    zoom: int = 12,
    size: str = "600x300",
    map_type: str = "roadmap",
) -> str | None:
    """
    Сформировать URL Static Maps API для отправки как фото в Telegram.
    waypoints: [{"lat": 13.75, "lng": 100.5}, ...]
    """
    key = settings.google_maps_api_key
    if not key or key == "placeholder":
        return None
    if not waypoints:
        return None

    markers = "&".join(
        f"markers=color:red%7C{p['lat']},{p['lng']}"
        for p in waypoints
    )
    path = "path=color:0x0000ff|weight:3|" + "|".join(
        f"{p['lat']},{p['lng']}" for p in waypoints
    ) if len(waypoints) > 1 else ""

    params = {
        "size": size,
        "maptype": map_type,
        "language": "ru",
        "key": key,
    }
    base = "https://maps.googleapis.com/maps/api/staticmap?" + urlencode(params)
    if path:
        base += f"&{path}"
    base += f"&{markers}"
    return base
