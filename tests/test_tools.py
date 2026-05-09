"""
Unit tests for app/tools/*.py

Tests pure functions without I/O and mock HTTP calls via pytest-httpx.
"""
import re
import pytest
from pytest_httpx import HTTPXMock


# ── Flights — pure functions ──────────────────────────────────────────────────

def test_city_to_iata_known():
    from app.tools.flights import city_to_iata
    assert city_to_iata("москва") == "MOW"
    assert city_to_iata("Бангкок") == "BKK"
    assert city_to_iata("бали") == "DPS"


def test_city_to_iata_unknown_returns_none():
    from app.tools.flights import city_to_iata
    # Unknown city → None (caller must handle)
    result = city_to_iata("xyz_unknown_city_99")
    assert result is None


def test_get_flight_link_with_date():
    from app.tools.flights import get_flight_link
    url = get_flight_link("MOW", "BKK", "2025-07-15")
    assert "aviasales.com" in url
    assert "MOW" in url
    assert "BKK" in url
    assert "15JUL" in url


def test_get_flight_link_no_date():
    from app.tools.flights import get_flight_link
    url = get_flight_link("LED", "DPS", None)
    assert "aviasales.com" in url
    assert "LED" in url
    assert "DPS" in url


def test_google_flights_link():
    from app.tools.flights import google_flights_link
    url = google_flights_link("Москва", "Бангкок")
    assert "google.com" in url
    assert "flights" in url


def test_format_flights_text_with_prices():
    from app.tools.flights import format_flights_text
    result = {
        "origin": "Москва",
        "destination": "Бангкок",
        "origin_iata": "MOW",
        "dest_iata": "BKK",
        "prices": [
            {
                "price": 350,
                "currency": "USD",
                "airline": "Thai Airways",
                "transfers": 1,
                "departure_at": "2025-07-15T10:00:00",
                "return_at": None,
            }
        ],
        "aviasales_link": "https://www.aviasales.com/search/MOW15JULBKK1",
        "google_link": "https://google.com/flights",
    }
    text = format_flights_text(result)
    assert "MOW" in text
    assert "BKK" in text
    assert "350" in text
    assert "Thai Airways" in text


def test_format_flights_text_empty_prices():
    from app.tools.flights import format_flights_text
    result = {
        "origin": "Москва",
        "destination": "Лондон",
        "origin_iata": "MOW",
        "dest_iata": "LHR",
        "prices": [],
        "aviasales_link": "https://www.aviasales.com/search/MOW0101LHR1",
        "google_link": "https://google.com/flights",
    }
    text = format_flights_text(result)
    assert isinstance(text, str)
    assert len(text) > 0


# ── Currency — pure functions ─────────────────────────────────────────────────

def test_get_cost_of_living_known():
    from app.tools.currency import get_cost_of_living
    col = get_cost_of_living("Бангкок")
    assert col is not None
    # CoL dict uses total_budget (not monthly_budget_usd)
    assert "total_budget" in col
    assert col["total_budget"] > 0
    assert "accommodation_budget" in col
    assert "food_budget" in col


def test_get_cost_of_living_bali_alias():
    from app.tools.currency import get_cost_of_living
    # Russian alias "бали" → "bali"
    col = get_cost_of_living("Бали")
    assert col is not None
    assert col["total_budget"] > 0


def test_get_cost_of_living_unknown():
    from app.tools.currency import get_cost_of_living
    assert get_cost_of_living("НесуществующийГород12345") is None


def test_format_cost_of_living():
    from app.tools.currency import format_cost_of_living
    # Use actual field names from the _COL dict
    col = {
        "city": "Тест",
        "total_budget": 1200,
        "total_comfortable": 2000,
        "accommodation_budget": 400,
        "accommodation_mid": 700,
        "food_budget": 300,
        "food_mid": 500,
        "transport": 50,
        "internet": 12,
        "coworking_day": 8,
        "currency": "USD",
        "notes": "Тест",
    }
    text = format_cost_of_living(col)
    assert "1200" in text
    assert isinstance(text, str)
    assert len(text) > 0


# ── Weather — mock HTTP ───────────────────────────────────────────────────────

async def test_get_forecast_weatherapi_success(httpx_mock: HTTPXMock):
    """WeatherAPI returns valid data → parsed into unified dict."""
    from unittest.mock import patch
    from app.tools import weather as weather_mod
    from app.tools.weather import get_forecast

    httpx_mock.add_response(
        url=re.compile(r"https://api\.weatherapi\.com/.*"),
        json={
            "location": {"name": "Bangkok", "country": "Thailand", "region": ""},
            "current": {
                "temp_c": 32.0,
                "feelslike_c": 36.0,
                "condition": {"text": "Sunny"},
                "humidity": 75,
                "wind_kph": 12.0,
                "wind_dir": "SE",
                "uv": 8,
                "precip_mm": 0,
            },
            "forecast": {
                "forecastday": [
                    {
                        "date": "2025-07-01",
                        "day": {
                            "maxtemp_c": 34,
                            "mintemp_c": 28,
                            "condition": {"text": "Sunny"},
                            "daily_chance_of_rain": 10,
                            "totalprecip_mm": 0,
                            "uv": 8,
                        },
                    }
                ]
            },
        },
    )

    # Patch the key so the code doesn't short-circuit
    with patch.object(weather_mod.settings, "weatherapi_key", "test-key-12345"):
        result = await get_forecast("Бангкок", days=1)

    assert result is not None
    assert result["temp_c"] == 32.0
    assert result["condition"] == "Sunny"
    assert result["humidity"] == 75


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_get_forecast_weatherapi_fails_owm_fallback(httpx_mock: HTTPXMock):
    """WeatherAPI 401 → tries OWM; if OWM key missing returns None."""
    from unittest.mock import patch
    from app.tools import weather as weather_mod
    from app.tools.weather import get_forecast

    httpx_mock.add_response(
        url=re.compile(r"https://api\.weatherapi\.com/.*"),
        status_code=401,
    )

    with patch.object(weather_mod.settings, "weatherapi_key", "test-key-12345"):
        result = await get_forecast("Бангкок", days=1)

    # OWM key is empty → returns None after WeatherAPI 401
    assert result is None


def test_get_best_season_known():
    from app.tools.weather import get_best_season
    import asyncio
    season = asyncio.run(get_best_season("Бангкок"))
    assert season is not None
    assert isinstance(season, str)


# ── Search — mock HTTP ────────────────────────────────────────────────────────

async def test_web_search_parse(httpx_mock: HTTPXMock):
    """DuckDuckGo Lite POST → results parsed."""
    from app.tools.search import web_search

    html = """
    <html><body><table>
    <tr><td class="result-link"><a href="https://example.com">Example Title</a></td></tr>
    <tr><td class="result-snippet">This is a test snippet about visas.</td></tr>
    </table></body></html>
    """
    httpx_mock.add_response(
        url="https://lite.duckduckgo.com/lite/",
        method="POST",
        text=html,
    )

    results = await web_search("виза Таиланд", max_results=3)
    assert isinstance(results, list)


async def test_web_search_error_returns_empty(httpx_mock: HTTPXMock):
    """Network error → returns empty list, no exception."""
    from app.tools.search import web_search

    httpx_mock.add_exception(
        url="https://lite.duckduckgo.com/lite/",
        exception=Exception("Connection refused"),
    )

    results = await web_search("test query")
    assert results == []
