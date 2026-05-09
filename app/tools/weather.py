"""Weather tools — WeatherAPI.com primary, OpenWeatherMap fallback."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)

# Унифицированный формат ответа
WeatherDict = dict[str, Any]

# Статичные данные о лучшем сезоне для популярных направлений
_BEST_SEASON: dict[str, str] = {
    "бангкок": "Ноябрь–февраль (сухой сезон, +28°C, нет дождей)",
    "bangkok": "Ноябрь–февраль (сухой сезон, +28°C, нет дождей)",
    "чиангмай": "Ноябрь–февраль (прохладно, +25°C, горы)",
    "chiang mai": "Ноябрь–февраль (прохладно, +25°C, горы)",
    "бали": "Апрель–октябрь (сухой сезон, +30°C)",
    "bali": "Апрель–октябрь (сухой сезон, +30°C)",
    "убуд": "Апрель–октябрь (сухой сезон, +28°C)",
    "ubud": "Апрель–октябрь (сухой сезон, +28°C)",
    "хошимин": "Декабрь–апрель (сухой сезон)",
    "ho chi minh": "Декабрь–апрель (сухой сезон)",
    "ханой": "Октябрь–апрель (прохладнее и суше)",
    "hanoi": "Октябрь–апрель (прохладнее и суше)",
    "да нанг": "Март–август (солнечно, +30°C)",
    "da nang": "Март–август (солнечно, +30°C)",
    "куала лумпур": "Март–апрель, июль–август (между муссонами)",
    "kuala lumpur": "Март–апрель, июль–август (между муссонами)",
    "сингапур": "Февраль–апрель (меньше дождей)",
    "singapore": "Февраль–апрель (меньше дождей)",
    "токио": "Март–май (сакура), октябрь–ноябрь (осень)",
    "tokyo": "Март–май (сакура), октябрь–ноябрь (осень)",
    "сеул": "Март–май и сентябрь–ноябрь",
    "seoul": "Март–май и сентябрь–ноябрь",
    "тбилиси": "Май–июнь и сентябрь–октябрь",
    "tbilisi": "Май–июнь и сентябрь–октябрь",
    "ереван": "Май–июнь и сентябрь–октябрь",
    "yerevan": "Май–июнь и сентябрь–октябрь",
    "стамбул": "Апрель–май и сентябрь–октябрь",
    "istanbul": "Апрель–май и сентябрь–октябрь",
    "лиссабон": "Май–октябрь (+25°C, солнечно)",
    "lisbon": "Май–октябрь (+25°C, солнечно)",
    "барселона": "Май–июнь и сентябрь (без толп)",
    "barcelona": "Май–июнь и сентябрь (без толп)",
    "берлин": "Май–сентябрь (+20°C, длинные дни)",
    "berlin": "Май–сентябрь (+20°C, длинные дни)",
    "прага": "Май–сентябрь (тепло и солнечно)",
    "prague": "Май–сентябрь (тепло и солнечно)",
    "будапешт": "Апрель–октябрь",
    "budapest": "Апрель–октябрь",
    "медельин": "Декабрь–март, июнь–июль (вечная весна +22°C)",
    "medellin": "Декабрь–март, июнь–июль (вечная весна +22°C)",
    "мехико": "Март–май (до сезона дождей)",
    "mexico city": "Март–май (до сезона дождей)",
    "буэнос айрес": "Октябрь–апрель (южное лето)",
    "buenos aires": "Октябрь–апрель (южное лето)",
}


def _unify_weatherapi(data: dict) -> WeatherDict:
    current = data["current"]
    location = data["location"]
    forecast_days = []
    for day in data.get("forecast", {}).get("forecastday", []):
        d = day["day"]
        forecast_days.append({
            "date": day["date"],
            "max_c": d["maxtemp_c"],
            "min_c": d["mintemp_c"],
            "condition": d["condition"]["text"],
            "rain_mm": d["totalprecip_mm"],
            "rain_chance": d.get("daily_chance_of_rain", 0),
            "uv": d.get("uv", 0),
        })
    return {
        "source": "weatherapi",
        "city": location["name"],
        "country": location["country"],
        "region": location.get("region", ""),
        "temp_c": current["temp_c"],
        "feels_like_c": current["feelslike_c"],
        "condition": current["condition"]["text"],
        "humidity": current["humidity"],
        "wind_kph": current["wind_kph"],
        "wind_dir": current.get("wind_dir", ""),
        "uv": current.get("uv", 0),
        "precip_mm": current.get("precip_mm", 0),
        "forecast": forecast_days,
    }


def _unify_openweather(data: dict) -> WeatherDict:
    main = data["main"]
    wind = data.get("wind", {})
    weather = data.get("weather", [{}])[0]
    return {
        "source": "openweathermap",
        "city": data.get("name", ""),
        "country": data.get("sys", {}).get("country", ""),
        "region": "",
        "temp_c": round(main["temp"], 1),
        "feels_like_c": round(main["feels_like"], 1),
        "condition": weather.get("description", ""),
        "humidity": main["humidity"],
        "wind_kph": round(wind.get("speed", 0) * 3.6, 1),
        "wind_dir": "",
        "uv": 0,
        "precip_mm": 0,
        "forecast": [],
    }


async def get_weather(city: str) -> WeatherDict | None:
    """Текущая погода. WeatherAPI → OWM fallback."""
    result = await _from_weatherapi(city, days=1)
    if result is None:
        result = await _from_openweather(city)
    return result


async def get_forecast(city: str, days: int = 7) -> WeatherDict | None:
    """Прогноз на N дней (максимум 7 для бесплатного плана WeatherAPI)."""
    days = min(days, 7)
    result = await _from_weatherapi(city, days=days)
    if result is None:
        result = await _from_openweather(city)
        if result:
            result["forecast"] = []
    return result


async def get_best_season(city: str) -> str:
    """Лучшее время для посещения города."""
    key = city.lower().strip()
    if key in _BEST_SEASON:
        return _BEST_SEASON[key]
    # Поиск по частичному совпадению
    for k, v in _BEST_SEASON.items():
        if k in key or key in k:
            return v
    return "Зависит от региона. Уточни запрос командой /weather для деталей."


# ── Private helpers ────────────────────────────────────────────────────────────

async def _from_weatherapi(city: str, days: int = 7) -> WeatherDict | None:
    key = settings.weatherapi_key
    if not key or key == "placeholder":
        return None
    url = "https://api.weatherapi.com/v1/forecast.json"
    params = {"key": key, "q": city, "days": days, "lang": "ru", "aqi": "no"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return _unify_weatherapi(r.json())
    except httpx.HTTPStatusError as e:
        logger.warning("WeatherAPI HTTP %s for city=%s", e.response.status_code, city)
        return None
    except Exception:
        logger.exception("WeatherAPI failed city=%s", city)
        return None


async def _from_openweather(city: str) -> WeatherDict | None:
    key = settings.openweather_api_key
    if not key or key == "placeholder":
        return None
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": key, "units": "metric", "lang": "ru"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return _unify_openweather(r.json())
    except httpx.HTTPStatusError as e:
        logger.warning("OpenWeather HTTP %s for city=%s", e.response.status_code, city)
        return None
    except Exception:
        logger.exception("OpenWeather failed city=%s", city)
        return None


def format_weather_text(w: WeatherDict) -> str:
    """Отформатировать погоду для отправки в Telegram (HTML)."""
    lines = [
        f"🌤 <b>{w['city']}, {w['country']}</b>",
        f"🌡 <b>{w['temp_c']}°C</b> (ощущается {w['feels_like_c']}°C)",
        f"☁️ {w['condition']}",
        f"💧 Влажность: {w['humidity']}%",
        f"💨 Ветер: {w['wind_kph']} км/ч",
    ]
    if w.get("forecast"):
        lines.append("\n━━━━━━━━━━━━━━━")
        lines.append("📅 <b>Прогноз:</b>")
        for day in w["forecast"][:7]:
            emoji = "🌧" if day["rain_mm"] > 5 else "☀️" if day["rain_chance"] < 20 else "⛅"
            lines.append(
                f"{emoji} {day['date']}: {day['min_c']}…{day['max_c']}°C, "
                f"{day['condition']}"
            )
    return "\n".join(lines)
