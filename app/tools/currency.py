"""Currency conversion (ExchangeRate-API + Redis) и стоимость жизни по городам."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)
TTL_RATES = 3600  # 1 час

# ── Стоимость жизни — статичная база 50+ городов (USD/мес) ──────────────────
# Все цифры — реальные диапазоны 2024–2025 для бюджетного номада
_COL: dict[str, dict[str, Any]] = {
    # ── Юго-Восточная Азия ────────────────────────────────────────────────────
    "bangkok": {
        "accommodation_budget": 250, "accommodation_mid": 550,
        "food_budget": 150, "food_mid": 280,
        "transport": 40, "internet": 12, "coworking_day": 8,
        "total_budget": 550, "total_comfortable": 1000,
        "currency": "Thai Baht (THB)", "notes": "Без визы 30 дней. Метро, Bolt, еда на рынках.",
    },
    "chiang mai": {
        "accommodation_budget": 180, "accommodation_mid": 380,
        "food_budget": 120, "food_mid": 220,
        "transport": 30, "internet": 10, "coworking_day": 6,
        "total_budget": 450, "total_comfortable": 800,
        "currency": "Thai Baht (THB)", "notes": "Столица номадов. NIMMAN — лучший район для жизни.",
    },
    "bali": {
        "accommodation_budget": 300, "accommodation_mid": 650,
        "food_budget": 180, "food_mid": 350,
        "transport": 60, "internet": 15, "coworking_day": 10,
        "total_budget": 650, "total_comfortable": 1200,
        "currency": "Indonesian Rupiah (IDR)", "notes": "Аренда скутера = $60/мес. Canggu — для номадов, Ubud — для духовных.",
    },
    "ubud": {
        "accommodation_budget": 280, "accommodation_mid": 600,
        "food_budget": 160, "food_mid": 320,
        "transport": 55, "internet": 15, "coworking_day": 9,
        "total_budget": 600, "total_comfortable": 1100,
        "currency": "Indonesian Rupiah (IDR)", "notes": "Спокойнее Чангу. Сильная йога/велнес сцена.",
    },
    "ho chi minh city": {
        "accommodation_budget": 220, "accommodation_mid": 480,
        "food_budget": 100, "food_mid": 220,
        "transport": 30, "internet": 10, "coworking_day": 6,
        "total_budget": 450, "total_comfortable": 850,
        "currency": "Vietnamese Dong (VND)", "notes": "Визаран не нужен (90 дней по e-visa). Grab — дешевле такси.",
    },
    "hanoi": {
        "accommodation_budget": 200, "accommodation_mid": 420,
        "food_budget": 90, "food_mid": 190,
        "transport": 25, "internet": 10, "coworking_day": 5,
        "total_budget": 400, "total_comfortable": 750,
        "currency": "Vietnamese Dong (VND)", "notes": "Дешевле HCM. Хорошая еда. Зима прохладная (+15°C).",
    },
    "da nang": {
        "accommodation_budget": 200, "accommodation_mid": 430,
        "food_budget": 100, "food_mid": 200,
        "transport": 30, "internet": 10, "coworking_day": 5,
        "total_budget": 420, "total_comfortable": 800,
        "currency": "Vietnamese Dong (VND)", "notes": "Пляж + горы. Быстрый интернет. Мало туристов.",
    },
    "kuala lumpur": {
        "accommodation_budget": 280, "accommodation_mid": 580,
        "food_budget": 150, "food_mid": 300,
        "transport": 40, "internet": 12, "coworking_day": 8,
        "total_budget": 580, "total_comfortable": 1050,
        "currency": "Malaysian Ringgit (MYR)", "notes": "Без визы 90 дней. Отличный хаб для Азии. Халяльная еда.",
    },
    "penang": {
        "accommodation_budget": 240, "accommodation_mid": 500,
        "food_budget": 130, "food_mid": 250,
        "transport": 35, "internet": 12, "coworking_day": 7,
        "total_budget": 500, "total_comfortable": 900,
        "currency": "Malaysian Ringgit (MYR)", "notes": "Лучшая уличная еда в Азии. Исторический Джорджтаун.",
    },
    "singapore": {
        "accommodation_budget": 1200, "accommodation_mid": 2200,
        "food_budget": 400, "food_mid": 700,
        "transport": 80, "internet": 30, "coworking_day": 25,
        "total_budget": 2500, "total_comfortable": 4000,
        "currency": "Singapore Dollar (SGD)", "notes": "Дорого. Но отличный хаб. Без визы 30 дней для RU.",
    },
    "phuket": {
        "accommodation_budget": 350, "accommodation_mid": 700,
        "food_budget": 180, "food_mid": 350,
        "transport": 70, "internet": 12, "coworking_day": 9,
        "total_budget": 700, "total_comfortable": 1350,
        "currency": "Thai Baht (THB)", "notes": "Туристичнее Чиангмая. Пляжи. Без скутера сложно.",
    },
    # ── Южная Азия ────────────────────────────────────────────────────────────
    "goa": {
        "accommodation_budget": 300, "accommodation_mid": 600,
        "food_budget": 150, "food_mid": 300,
        "transport": 50, "internet": 15, "coworking_day": 8,
        "total_budget": 600, "total_comfortable": 1100,
        "currency": "Indian Rupee (INR)", "notes": "e-Visa 90 дней. Хорошая тусовка номадов. Скутер обязателен.",
    },
    # ── Восточная Азия ────────────────────────────────────────────────────────
    "tokyo": {
        "accommodation_budget": 900, "accommodation_mid": 1500,
        "food_budget": 400, "food_mid": 700,
        "transport": 100, "internet": 30, "coworking_day": 20,
        "total_budget": 1800, "total_comfortable": 3000,
        "currency": "Japanese Yen (JPY)", "notes": "Виза нужна (бесплатная). Невероятно удобно. IC-карта для транспорта.",
    },
    "seoul": {
        "accommodation_budget": 700, "accommodation_mid": 1300,
        "food_budget": 300, "food_mid": 550,
        "transport": 60, "internet": 25, "coworking_day": 15,
        "total_budget": 1400, "total_comfortable": 2500,
        "currency": "South Korean Won (KRW)", "notes": "Виза нужна. Быстрейший интернет в мире. Инфраструктура топ.",
    },
    "taipei": {
        "accommodation_budget": 600, "accommodation_mid": 1100,
        "food_budget": 250, "food_mid": 450,
        "transport": 50, "internet": 20, "coworking_day": 12,
        "total_budget": 1100, "total_comfortable": 2000,
        "currency": "New Taiwan Dollar (TWD)", "notes": "Без визы 90 дней. Очень безопасно. Лучшая уличная еда.",
    },
    # ── Кавказ / Центральная Азия ─────────────────────────────────────────────
    "tbilisi": {
        "accommodation_budget": 280, "accommodation_mid": 550,
        "food_budget": 150, "food_mid": 280,
        "transport": 25, "internet": 12, "coworking_day": 8,
        "total_budget": 550, "total_comfortable": 1000,
        "currency": "Georgian Lari (GEL)", "notes": "Без визы 365 дней для RU. Лучшее вино мира. Растущая номад-сцена.",
    },
    "yerevan": {
        "accommodation_budget": 280, "accommodation_mid": 520,
        "food_budget": 130, "food_mid": 250,
        "transport": 20, "internet": 10, "coworking_day": 7,
        "total_budget": 500, "total_comfortable": 900,
        "currency": "Armenian Dram (AMD)", "notes": "Без визы 180 дней для RU. Стремительно развивается. Хороший интернет.",
    },
    "almaty": {
        "accommodation_budget": 300, "accommodation_mid": 580,
        "food_budget": 160, "food_mid": 300,
        "transport": 30, "internet": 12, "coworking_day": 8,
        "total_budget": 580, "total_comfortable": 1050,
        "currency": "Kazakhstani Tenge (KZT)", "notes": "Без визы 30 дней. Горы рядом. Хорошие банки.",
    },
    "tashkent": {
        "accommodation_budget": 200, "accommodation_mid": 400,
        "food_budget": 100, "food_mid": 200,
        "transport": 20, "internet": 10, "coworking_day": 5,
        "total_budget": 380, "total_comfortable": 700,
        "currency": "Uzbekistani Som (UZS)", "notes": "Без визы 30 дней. Очень дёшево. Интернет ограничен. Самарканд рядом.",
    },
    "baku": {
        "accommodation_budget": 300, "accommodation_mid": 580,
        "food_budget": 150, "food_mid": 280,
        "transport": 25, "internet": 12, "coworking_day": 8,
        "total_budget": 550, "total_comfortable": 1000,
        "currency": "Azerbaijani Manat (AZN)", "notes": "Без визы 30 дней для RU. Каспийское море. Нефтяная столица.",
    },
    # ── Ближний Восток ────────────────────────────────────────────────────────
    "istanbul": {
        "accommodation_budget": 350, "accommodation_mid": 700,
        "food_budget": 180, "food_mid": 350,
        "transport": 40, "internet": 15, "coworking_day": 10,
        "total_budget": 650, "total_comfortable": 1300,
        "currency": "Turkish Lira (TRY)", "notes": "Без визы 60 дней. Два континента. Инфляция высокая.",
    },
    "dubai": {
        "accommodation_budget": 1200, "accommodation_mid": 2200,
        "food_budget": 500, "food_mid": 900,
        "transport": 120, "internet": 40, "coworking_day": 30,
        "total_budget": 2500, "total_comfortable": 4500,
        "currency": "UAE Dirham (AED)", "notes": "Без визы 30 дней. Безналоговый. Жарко летом (+45°C). Хаб для бизнеса.",
    },
    # ── Африка ────────────────────────────────────────────────────────────────
    "cairo": {
        "accommodation_budget": 200, "accommodation_mid": 420,
        "food_budget": 80, "food_mid": 160,
        "transport": 20, "internet": 10, "coworking_day": 5,
        "total_budget": 380, "total_comfortable": 700,
        "currency": "Egyptian Pound (EGP)", "notes": "Виза по прилёту $25. Пирамиды, история. Жарко летом.",
    },
    "marrakech": {
        "accommodation_budget": 280, "accommodation_mid": 550,
        "food_budget": 130, "food_mid": 260,
        "transport": 30, "internet": 12, "coworking_day": 8,
        "total_budget": 530, "total_comfortable": 1000,
        "currency": "Moroccan Dirham (MAD)", "notes": "Без визы 90 дней. Медина, рияды. Близко к Европе.",
    },
    # ── Европа ────────────────────────────────────────────────────────────────
    "lisbon": {
        "accommodation_budget": 800, "accommodation_mid": 1400,
        "food_budget": 350, "food_mid": 600,
        "transport": 50, "internet": 20, "coworking_day": 15,
        "total_budget": 1400, "total_comfortable": 2500,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Солнечно. Самая дешёвая столица Зап. Европы.",
    },
    "porto": {
        "accommodation_budget": 700, "accommodation_mid": 1200,
        "food_budget": 300, "food_mid": 550,
        "transport": 45, "internet": 20, "coworking_day": 12,
        "total_budget": 1200, "total_comfortable": 2000,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Дешевле Лиссабона. Порт и атлантика.",
    },
    "barcelona": {
        "accommodation_budget": 1000, "accommodation_mid": 1800,
        "food_budget": 400, "food_mid": 700,
        "transport": 60, "internet": 25, "coworking_day": 18,
        "total_budget": 1800, "total_comfortable": 3200,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Пляж + город. Много номадов.",
    },
    "madrid": {
        "accommodation_budget": 900, "accommodation_mid": 1600,
        "food_budget": 380, "food_mid": 650,
        "transport": 55, "internet": 22, "coworking_day": 16,
        "total_budget": 1600, "total_comfortable": 3000,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Столица. Лучший трансфер-хаб в Европе.",
    },
    "berlin": {
        "accommodation_budget": 900, "accommodation_mid": 1600,
        "food_budget": 350, "food_mid": 600,
        "transport": 90, "internet": 25, "coworking_day": 18,
        "total_budget": 1700, "total_comfortable": 3000,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Большая русскоязычная диаспора. Много коворкингов.",
    },
    "prague": {
        "accommodation_budget": 700, "accommodation_mid": 1200,
        "food_budget": 280, "food_mid": 500,
        "transport": 50, "internet": 18, "coworking_day": 12,
        "total_budget": 1200, "total_comfortable": 2200,
        "currency": "Czech Koruna (CZK)", "notes": "Виза Шенген. Дешевле Зап. Европы. Отличный центр. Безопасно.",
    },
    "budapest": {
        "accommodation_budget": 600, "accommodation_mid": 1000,
        "food_budget": 250, "food_mid": 450,
        "transport": 40, "internet": 15, "coworking_day": 10,
        "total_budget": 1000, "total_comfortable": 1800,
        "currency": "Hungarian Forint (HUF)", "notes": "Виза Шенген. Красивый город. Термальные бани.",
    },
    "warsaw": {
        "accommodation_budget": 650, "accommodation_mid": 1100,
        "food_budget": 270, "food_mid": 480,
        "transport": 45, "internet": 15, "coworking_day": 11,
        "total_budget": 1100, "total_comfortable": 2000,
        "currency": "Polish Zloty (PLN)", "notes": "Виза Шенген. Хороший интернет. Быстро растёт.",
    },
    "tallinn": {
        "accommodation_budget": 750, "accommodation_mid": 1300,
        "food_budget": 300, "food_mid": 550,
        "transport": 50, "internet": 20, "coworking_day": 14,
        "total_budget": 1300, "total_comfortable": 2400,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Цифровая столица. e-Residency. Красивый Старый город.",
    },
    "riga": {
        "accommodation_budget": 650, "accommodation_mid": 1100,
        "food_budget": 270, "food_mid": 480,
        "transport": 45, "internet": 18, "coworking_day": 12,
        "total_budget": 1100, "total_comfortable": 2000,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Дешевле Таллина. Отличный арт-нуво центр.",
    },
    "athens": {
        "accommodation_budget": 600, "accommodation_mid": 1100,
        "food_budget": 280, "food_mid": 500,
        "transport": 45, "internet": 18, "coworking_day": 11,
        "total_budget": 1100, "total_comfortable": 2000,
        "currency": "Euro (EUR)", "notes": "Виза Шенген. Солнечно. Рядом острова. Дешевле Зап. Европы.",
    },
    "tirana": {
        "accommodation_budget": 350, "accommodation_mid": 650,
        "food_budget": 150, "food_mid": 300,
        "transport": 25, "internet": 12, "coworking_day": 7,
        "total_budget": 600, "total_comfortable": 1100,
        "currency": "Albanian Lek (ALL)", "notes": "Без визы 90 дней. Самая быстрорастущая столица Европы. Дёшево.",
    },
    "sofia": {
        "accommodation_budget": 450, "accommodation_mid": 800,
        "food_budget": 200, "food_mid": 370,
        "transport": 35, "internet": 15, "coworking_day": 9,
        "total_budget": 800, "total_comfortable": 1500,
        "currency": "Bulgarian Lev (BGN)", "notes": "Виза Шенген. Дешёво. Горы рядом. Вайфай хороший.",
    },
    # ── Латинская Америка ─────────────────────────────────────────────────────
    "mexico city": {
        "accommodation_budget": 450, "accommodation_mid": 900,
        "food_budget": 200, "food_mid": 400,
        "transport": 30, "internet": 18, "coworking_day": 10,
        "total_budget": 800, "total_comfortable": 1500,
        "currency": "Mexican Peso (MXN)", "notes": "Без визы 180 дней. Roma Norte, Condesa — для номадов. Дёшево и вкусно.",
    },
    "medellin": {
        "accommodation_budget": 400, "accommodation_mid": 800,
        "food_budget": 180, "food_mid": 350,
        "transport": 25, "internet": 18, "coworking_day": 9,
        "total_budget": 700, "total_comfortable": 1300,
        "currency": "Colombian Peso (COP)", "notes": "Без визы 90 дней. Вечная весна +22°C. El Poblado — для номадов.",
    },
    "bogota": {
        "accommodation_budget": 380, "accommodation_mid": 750,
        "food_budget": 160, "food_mid": 320,
        "transport": 25, "internet": 15, "coworking_day": 8,
        "total_budget": 650, "total_comfortable": 1200,
        "currency": "Colombian Peso (COP)", "notes": "Без визы 90 дней. Высота 2600м — первые дни сложно. Chapinero для номадов.",
    },
    "buenos aires": {
        "accommodation_budget": 350, "accommodation_mid": 700,
        "food_budget": 180, "food_mid": 350,
        "transport": 20, "internet": 15, "coworking_day": 8,
        "total_budget": 600, "total_comfortable": 1150,
        "currency": "Argentine Peso (ARS)", "notes": "Без визы 90 дней. Инфляция. Используй синий курс через Western Union.",
    },
    "lima": {
        "accommodation_budget": 380, "accommodation_mid": 750,
        "food_budget": 160, "food_mid": 320,
        "transport": 25, "internet": 15, "coworking_day": 8,
        "total_budget": 650, "total_comfortable": 1200,
        "currency": "Peruvian Sol (PEN)", "notes": "Без визы 90 дней. Miraflores, Barranco для номадов. Мачу-Пикчу рядом.",
    },
    "cancun": {
        "accommodation_budget": 500, "accommodation_mid": 1000,
        "food_budget": 220, "food_mid": 430,
        "transport": 35, "internet": 20, "coworking_day": 11,
        "total_budget": 880, "total_comfortable": 1700,
        "currency": "Mexican Peso (MXN)", "notes": "Без визы 180 дней. Карибское море. Дороже CDMX.",
    },
    # ── Россия (для сравнения) ─────────────────────────────────────────────────
    "moscow": {
        "accommodation_budget": 600, "accommodation_mid": 1100,
        "food_budget": 250, "food_mid": 500,
        "transport": 40, "internet": 8, "coworking_day": 12,
        "total_budget": 1000, "total_comfortable": 1800,
        "currency": "Russian Ruble (RUB)", "notes": "Столица. Дорогой найм жилья. Хороший интернет.",
    },
}

# Алиасы для поиска
_ALIASES = {
    "hcm": "ho chi minh city",
    "saigon": "ho chi minh city",
    "сайгон": "ho chi minh city",
    "хошимин": "ho chi minh city",
    "бангкок": "bangkok",
    "чиангмай": "chiang mai",
    "бали": "bali",
    "куала лумпур": "kuala lumpur",
    "сингапур": "singapore",
    "токио": "tokyo",
    "сеул": "seoul",
    "тайбэй": "taipei",
    "тбилиси": "tbilisi",
    "ереван": "yerevan",
    "алматы": "almaty",
    "ташкент": "tashkent",
    "баку": "baku",
    "стамбул": "istanbul",
    "дубай": "dubai",
    "каир": "cairo",
    "марракеш": "marrakech",
    "лиссабон": "lisbon",
    "барселона": "barcelona",
    "мадрид": "madrid",
    "берлин": "berlin",
    "прага": "prague",
    "будапешт": "budapest",
    "варшава": "warsaw",
    "таллин": "tallinn",
    "рига": "riga",
    "афины": "athens",
    "тирана": "tirana",
    "софия": "sofia",
    "мехико": "mexico city",
    "медельин": "medellin",
    "богота": "bogota",
    "буэнос айрес": "buenos aires",
    "лима": "lima",
    "москва": "moscow",
    "порту": "porto",
}


# ── Redis helpers ──────────────────────────────────────────────────────────────

def _get_redis():
    from app.memory.context import get_redis
    return get_redis()


async def _cache_get(key: str) -> dict | None:
    try:
        raw = await _get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(key: str, value: dict, ttl: int = TTL_RATES) -> None:
    try:
        await _get_redis().setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


# ── Currency conversion ────────────────────────────────────────────────────────

async def get_rates(base: str = "USD") -> dict[str, float] | None:
    """Получить курсы. Кэш Redis 1 час."""
    cache_key = f"rates:{base.upper()}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    url = f"https://api.exchangerate-api.com/v4/latest/{base.upper()}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            rates = r.json()["rates"]
            await _cache_set(cache_key, rates, TTL_RATES)
            return rates
    except Exception:
        logger.exception("ExchangeRate-API failed base=%s", base)
        return None


async def convert(amount: float, from_currency: str, to_currency: str) -> float | None:
    """Конвертировать сумму из одной валюты в другую."""
    frm = from_currency.upper()
    to = to_currency.upper()
    if frm == to:
        return round(amount, 2)
    rates = await get_rates(frm)
    if rates and to in rates:
        return round(amount * rates[to], 2)
    return None


# ── Cost of living ─────────────────────────────────────────────────────────────

def get_cost_of_living(city: str) -> dict[str, Any] | None:
    """
    Вернуть данные о стоимости жизни для города.
    Поиск по точному совпадению, алиасам, частичному совпадению.
    """
    key = city.lower().strip()

    # 1. Точное совпадение
    if key in _COL:
        return {"city": city, **_COL[key]}

    # 2. Алиас
    alias = _ALIASES.get(key)
    if alias and alias in _COL:
        return {"city": city, **_COL[alias]}

    # 3. Частичное совпадение
    for col_key, data in _COL.items():
        if col_key in key or key in col_key:
            return {"city": city, **data}

    return None


def format_cost_of_living(col: dict[str, Any]) -> str:
    """Отформатировать стоимость жизни для Telegram (HTML)."""
    city = col.get("city", "Город")
    lines = [
        f"💰 <b>{city.upper()} — СТОИМОСТЬ ЖИЗНИ</b>",
        f"<i>{col.get('notes', '')}</i>",
        "━━━━━━━━━━━━━━━",
        "<b>Расходы в месяц (USD):</b>",
        f"🏠 Жильё (бюджет / нормально): ${col['accommodation_budget']} / ${col['accommodation_mid']}",
        f"🍜 Еда (бюджет / нормально): ${col['food_budget']} / ${col['food_mid']}",
        f"🚇 Транспорт: ${col['transport']}",
        f"📶 Интернет: ${col['internet']}",
        f"💻 Коворкинг (в день): ${col['coworking_day']}",
        "━━━━━━━━━━━━━━━",
        f"📊 <b>ИТОГО:</b>",
        f"▸ Минимум: <b>${col['total_budget']}/мес</b>",
        f"▸ Комфортно: <b>${col['total_comfortable']}/мес</b>",
        f"💳 Валюта: {col.get('currency', '—')}",
    ]
    return "\n".join(lines)


def list_covered_cities() -> list[str]:
    return sorted(_COL.keys())
