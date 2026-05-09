"""Flights — Travelpayouts Data API + Aviasales deeplinks + Google Flights fallback."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)

# ── IATA маппинг (город → основной аэропорт) ──────────────────────────────────
_CITY_TO_IATA: dict[str, str] = {
    # Россия и СНГ
    "москва": "MOW", "moscow": "MOW",
    "санкт-петербург": "LED", "питер": "LED", "saint petersburg": "LED",
    "новосибирск": "OVB", "екатеринбург": "SVX", "казань": "KZN",
    "тбилиси": "TBS", "tbilisi": "TBS",
    "ереван": "EVN", "yerevan": "EVN",
    "алматы": "ALA", "almaty": "ALA",
    "ташкент": "TAS", "tashkent": "TAS",
    "баку": "GYD", "baku": "GYD",
    "минск": "MSQ", "minsk": "MSQ",
    # Азия
    "бангкок": "BKK", "bangkok": "BKK",
    "пхукет": "HKT", "phuket": "HKT",
    "чиангмай": "CNX", "chiang mai": "CNX",
    "бали": "DPS", "bali": "DPS", "денпасар": "DPS", "denpasar": "DPS",
    "хошимин": "SGN", "ho chi minh": "SGN", "saigon": "SGN",
    "ханой": "HAN", "hanoi": "HAN",
    "да нанг": "DAD", "da nang": "DAD",
    "куала лумпур": "KUL", "kuala lumpur": "KUL",
    "сингапур": "SIN", "singapore": "SIN",
    "токио": "TYO", "tokyo": "TYO",
    "осака": "OSA", "osaka": "OSA",
    "сеул": "SEL", "seoul": "SEL",
    "пекин": "BJS", "beijing": "BJS",
    "шанхай": "SHA", "shanghai": "SHA",
    "тайбэй": "TPE", "taipei": "TPE",
    "гоа": "GOI", "goa": "GOI",
    "мумбаи": "BOM", "mumbai": "BOM", "бомбей": "BOM",
    "дели": "DEL", "delhi": "DEL", "new delhi": "DEL",
    "катманду": "KTM", "kathmandu": "KTM",
    "коломбо": "CMB", "colombo": "CMB",
    # Ближний Восток
    "стамбул": "IST", "istanbul": "IST",
    "дубай": "DXB", "dubai": "DXB",
    "абу дабиа": "AUH", "abu dhabi": "AUH",
    "доха": "DOH", "doha": "DOH",
    "тель авив": "TLV", "tel aviv": "TLV",
    "каир": "CAI", "cairo": "CAI",
    "амман": "AMM", "amman": "AMM",
    # Европа
    "лиссабон": "LIS", "lisbon": "LIS",
    "порту": "OPO", "porto": "OPO",
    "мадрид": "MAD", "madrid": "MAD",
    "барселона": "BCN", "barcelona": "BCN",
    "берлин": "BER", "berlin": "BER",
    "мюнхен": "MUC", "munich": "MUC",
    "франкфурт": "FRA", "frankfurt": "FRA",
    "вена": "VIE", "vienna": "VIE",
    "прага": "PRG", "prague": "PRG",
    "варшава": "WAW", "warsaw": "WAW",
    "будапешт": "BUD", "budapest": "BUD",
    "рига": "RIX", "riga": "RIX",
    "таллин": "TLL", "tallinn": "TLL",
    "вильнюс": "VNO", "vilnius": "VNO",
    "хельсинки": "HEL", "helsinki": "HEL",
    "копенгаген": "CPH", "copenhagen": "CPH",
    "амстердам": "AMS", "amsterdam": "AMS",
    "брюссель": "BRU", "brussels": "BRU",
    "париж": "PAR", "paris": "PAR",
    "лондон": "LON", "london": "LON",
    "рим": "ROM", "rome": "ROM",
    "милан": "MIL", "milan": "MIL",
    "афины": "ATH", "athens": "ATH",
    "бухарест": "OTP", "bucharest": "OTP",
    "софия": "SOF", "sofia": "SOF",
    "белград": "BEG", "belgrade": "BEG",
    "загреб": "ZAG", "zagreb": "ZAG",
    "тирана": "TIA", "tirana": "TIA",
    # Африка
    "марракеш": "RAK", "marrakech": "RAK",
    "касабланка": "CMN", "casablanca": "CMN",
    "найроби": "NBO", "nairobi": "NBO",
    "йоханнесбург": "JNB", "johannesburg": "JNB",
    # Латинская Америка
    "мехико": "MEX", "mexico city": "MEX",
    "канкун": "CUN", "cancun": "CUN",
    "лима": "LIM", "lima": "LIM",
    "богота": "BOG", "bogota": "BOG",
    "медельин": "MDE", "medellin": "MDE",
    "буэнос айрес": "BUE", "buenos aires": "BUE",
    "сан паулу": "SAO", "sao paulo": "SAO",
    "рио де жанейро": "RIO", "rio de janeiro": "RIO",
    "сантьяго": "SCL", "santiago": "SCL",
    # Северная Америка
    "нью йорк": "NYC", "new york": "NYC",
    "лос анджелес": "LAX", "los angeles": "LAX",
    "майами": "MIA", "miami": "MIA",
    "чикаго": "CHI", "chicago": "CHI",
    "торонто": "YTO", "toronto": "YTO",
    "ванкувер": "YVR", "vancouver": "YVR",
    # Океания
    "сидней": "SYD", "sydney": "SYD",
    "мельбурн": "MEL", "melbourne": "MEL",
    "бангалор": "BLR", "bangalore": "BLR",
}


def city_to_iata(city: str) -> str | None:
    """Получить IATA-код по названию города (регистронезависимо)."""
    return _CITY_TO_IATA.get(city.lower().strip())


# ── Travelpayouts API ──────────────────────────────────────────────────────────

async def search_cached_prices(
    origin_iata: str,
    dest_iata: str,
    currency: str = "usd",
) -> list[dict[str, Any]]:
    """
    Кэшированные цены Travelpayouts (последние найденные билеты).
    Возвращает список {price, airline, departure_at, return_at, link}.
    """
    token = settings.travelpayouts_token
    if not token or token == "placeholder":
        logger.warning("TRAVELPAYOUTS_TOKEN not set")
        return []

    url = "https://api.travelpayouts.com/aviasales/v3/get_latest_prices"
    params = {
        "origin": origin_iata.upper(),
        "destination": dest_iata.upper(),
        "currency": currency,
        "period_type": "year",
        "one_way": "false",
        "limit": 5,
        "show_to_affiliates": "true",
        "token": token,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

        if not data.get("success") or not data.get("data"):
            return []

        results = []
        for item in data["data"][:5]:
            results.append({
                "price": item.get("price"),
                "currency": currency.upper(),
                "airline": item.get("airline", ""),
                "departure_at": item.get("departure_at", ""),
                "return_at": item.get("return_at", ""),
                "transfers": item.get("transfers", 0),
                "link": f"https://www.aviasales.com{item.get('link', '')}",
            })
        return results

    except httpx.HTTPStatusError as e:
        logger.warning("Travelpayouts HTTP %s origin=%s dest=%s", e.response.status_code, origin_iata, dest_iata)
        return []
    except Exception:
        logger.exception("Travelpayouts failed origin=%s dest=%s", origin_iata, dest_iata)
        return []


async def search_flights(
    origin: str,
    destination: str,
    date: str | None = None,
) -> dict[str, Any]:
    """
    Высокоуровневый поиск: принимает названия городов, возвращает результаты + ссылки.
    date format: YYYY-MM-DD (опционально)
    """
    origin_iata = city_to_iata(origin) or origin.upper()[:3]
    dest_iata = city_to_iata(destination) or destination.upper()[:3]

    prices = await search_cached_prices(origin_iata, dest_iata)

    return {
        "origin": origin,
        "destination": destination,
        "origin_iata": origin_iata,
        "dest_iata": dest_iata,
        "date": date,
        "prices": prices,
        "aviasales_link": get_flight_link(origin_iata, dest_iata, date),
        "google_link": google_flights_link(origin, destination),
    }


# ── Deeplinks ─────────────────────────────────────────────────────────────────

def get_flight_link(
    origin_iata: str,
    dest_iata: str,
    date: str | None = None,
) -> str:
    """
    Deeplink на Aviasales.
    date: YYYY-MM-DD → DDMMM (01JAN)
    """
    _MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    if date:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_str = f"{dt.day:02d}{_MON[dt.month - 1]}"
        except ValueError:
            date_str = "0101"
    else:
        date_str = "0101"
    o = origin_iata.upper()
    d = dest_iata.upper()
    return f"https://www.aviasales.com/search/{o}{date_str}{d}1"


def google_flights_link(origin: str, destination: str) -> str:
    """Fallback ссылка на Google Flights."""
    from urllib.parse import quote
    q = quote(f"flights from {origin} to {destination}")
    return f"https://www.google.com/travel/flights/search?q={q}"


def format_flights_text(result: dict[str, Any]) -> str:
    """Отформатировать результаты поиска для Telegram (HTML)."""
    o = result["origin"]
    d = result["destination"]
    o_iata = result["origin_iata"]
    d_iata = result["dest_iata"]

    lines = [
        f"✈️ <b>{o.upper()} ({o_iata}) → {d.upper()} ({d_iata})</b>",
        "━━━━━━━━━━━━━━━",
    ]

    prices = result.get("prices", [])
    if prices:
        lines.append("<b>Найденные цены:</b>")
        for p in prices:
            transfers = "прямой" if p["transfers"] == 0 else f"{p['transfers']} пересадка"
            dep = p.get("departure_at", "")[:10] if p.get("departure_at") else ""
            dep_str = f" · {dep}" if dep else ""
            lines.append(
                f"▸ <b>${p['price']}</b> {transfers}{dep_str}"
                f" [{p.get('airline', '')}]"
            )
        lines.append("")
    else:
        lines.append("📡 Кэшированных цен нет — посмотри по ссылкам ниже.")
        lines.append("")

    lines += [
        f"🔍 <a href=\"{result['aviasales_link']}\">Поиск на Aviasales</a>",
        f"🔍 <a href=\"{result['google_link']}\">Поиск на Google Flights</a>",
    ]
    return "\n".join(lines)
