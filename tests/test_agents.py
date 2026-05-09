"""
Unit tests for app/agents/*.py

Agents are tested with mocked LLM (_llm patched in conftest via autouse),
mocked SharedContext (mock_ctx fixture), and mocked tool functions.
"""
import pytest
from unittest.mock import AsyncMock, patch


# ── Orchestrator — intent classification ─────────────────────────────────────

async def test_classify_intent_visa_keywords():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("Нужна ли виза в Таиланд?")
    assert "visa" in intents


async def test_classify_intent_weather_keywords():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("какая погода в Бангкоке?")
    assert "weather" in intents


async def test_classify_intent_flights_keywords():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("билеты из Москвы в Пхукет")
    assert "flights" in intents


async def test_classify_intent_budget_keywords():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("какой бюджет нужен для жизни в Бали?")
    assert "budget" in intents


async def test_classify_intent_worldtrip():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("хочу кругосветку на 6 месяцев")
    assert "worldtrip" in intents


async def test_classify_intent_multiple():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    intents = await orch.classify_intent("погода и стоимость жизни в Чиангмае")
    assert "weather" in intents
    assert "budget" in intents


# ── Orchestrator — full run with mocked agents ───────────────────────────────

async def test_orchestrator_run_returns_text(mock_ctx):
    """Orchestrator.run() returns a dict with 'text' key."""
    from app.agents.orchestrator import Orchestrator

    with patch("app.agents.orchestrator.Orchestrator._build_tasks") as mock_tasks:
        async def fake_agent():
            return {"budget": {"monthly_budget_usd": 1000}, "budget_text": "$1000/мес"}

        mock_tasks.return_value = [fake_agent()]

        orch = Orchestrator()
        result = await orch.run("стоимость жизни Бангкок", user_id=12345)

    assert "text" in result
    assert isinstance(result["text"], str)
    assert len(result["text"]) > 0


async def test_orchestrator_synthesize_returns_string():
    from app.agents.orchestrator import Orchestrator
    orch = Orchestrator()
    text = await orch.synthesize_results(
        query="Таиланд бюджет",
        data={"budget": {"monthly_budget_usd": 1200}, "budget_text": "$1200/мес"},
    )
    assert isinstance(text, str)


# ── BudgetAgent ───────────────────────────────────────────────────────────────

async def test_budget_agent_calculate_known_city():
    from app.agents.budget_agent import BudgetAgent
    agent = BudgetAgent()
    result = await agent.calculate("Бангкок", budget_usd=1500)
    assert result.get("error") is None, f"Unexpected error: {result}"
    assert result["city"] == "Бангкок"
    assert "monthly_usd" in result
    assert result["monthly_usd"] > 0  # total_budget for Bangkok is 550
    assert "feasible" in result
    assert result["feasible"] is True  # 1500 >= 550


async def test_budget_agent_calculate_unknown_city():
    from app.agents.budget_agent import BudgetAgent
    agent = BudgetAgent()
    result = await agent.calculate("НесуществующийГород", budget_usd=1500)
    assert result.get("error") == "city_not_found"


async def test_budget_agent_compare_cities():
    from app.agents.budget_agent import BudgetAgent
    agent = BudgetAgent()
    results = await agent.compare_cities(["Бангкок", "Бали", "Тбилиси"], budget_usd=1500)
    assert isinstance(results, list)
    assert len(results) >= 1
    # Should be sorted by monthly cost ascending
    costs = [r["monthly_usd"] for r in results]
    assert costs == sorted(costs)


async def test_budget_agent_run_with_ctx(mock_ctx):
    from app.agents.budget_agent import BudgetAgent
    agent = BudgetAgent()
    result = await agent.run("Бангкок", mock_ctx)
    assert "budget" in result or "error" in result


# ── FlightAgent ───────────────────────────────────────────────────────────────

async def test_flight_agent_no_destination(mock_ctx):
    from app.agents.flight_agent import FlightAgent
    agent = FlightAgent()
    result = await agent.run("Москва", mock_ctx)
    assert result.get("error") == "no_destination"


async def test_flight_agent_search_returns_structure():
    from app.agents.flight_agent import FlightAgent

    async def mock_search(origin, dest, date=None):
        return {
            "origin": "Москва",
            "destination": "Бангкок",
            "origin_iata": "MOW",
            "dest_iata": "BKK",
            "date": date,
            "prices": [
                {"price": 400, "currency": "USD", "airline": "Test Air",
                 "transfers": 1, "departure_at": "2025-07-01", "return_at": None}
            ],
            "aviasales_link": "https://aviasales.com/search/MOW0101BKK1",
            "google_link": "https://google.com/flights",
        }

    with patch("app.agents.flight_agent.search_flights", mock_search):
        agent = FlightAgent()
        result = await agent.search("MOW", "BKK", "2025-07-01")

    assert "flights" in result
    assert "deeplink" in result
    assert "text" in result


# ── WeatherAgent ──────────────────────────────────────────────────────────────

async def test_weather_agent_unavailable(mock_ctx):
    """Weather unavailable → returns error key, no exception."""
    from app.agents.weather_agent import WeatherAgent

    with patch("app.agents.weather_agent.get_forecast", AsyncMock(return_value=None)):
        with patch("app.agents.weather_agent.get_best_season", AsyncMock(return_value="ноябрь-март")):
            agent = WeatherAgent()
            result = await agent.run("Бангкок", mock_ctx)

    assert result.get("error") == "weather_unavailable"
    assert result.get("season") == "ноябрь-март"


async def test_weather_agent_success(mock_ctx):
    from app.agents.weather_agent import WeatherAgent

    fake_weather = {
        "temp_c": 30.0,
        "feels_like_c": 33.0,
        "condition": "Sunny",
        "humidity": 70,
        "wind_kph": 10.0,
        "forecast": [],
        "source": "weatherapi",
    }

    with patch("app.agents.weather_agent.get_forecast", AsyncMock(return_value=fake_weather)):
        with patch("app.agents.weather_agent.get_best_season", AsyncMock(return_value="ноябрь-март")):
            with patch("app.agents.weather_agent.format_weather_text", return_value="30°C, Sunny"):
                agent = WeatherAgent()
                result = await agent.run("Бангкок", mock_ctx)

    assert "weather" in result
    assert result["weather"]["temp_c"] == 30.0
    assert "weather_advice" in result


# ── VisaAgent ─────────────────────────────────────────────────────────────────

async def test_visa_agent_run(mock_ctx):
    from app.agents.visa_agent import VisaAgent

    with patch("app.agents.visa_agent.search_travel_info", AsyncMock(return_value=[
        {"title": "Виза в Таиланд 2025", "snippet": "Безвизовый въезд 30 дней", "url": "https://example.com"}
    ])):
        agent = VisaAgent()
        result = await agent.run("Таиланд", mock_ctx)

    assert "visa" in result
    assert result["visa"]["country"] == "Таиланд"
    assert result["visa"]["passport"] == "Россия"
    assert "visa_text" in result


# ── WorldTripAgent ────────────────────────────────────────────────────────────

def test_worldtrip_budget_tier_low():
    from app.agents.worldtrip_agent import WorldTripAgent
    agent = WorldTripAgent()
    assert agent._budget_tier(900) == "бюджетный"


def test_worldtrip_budget_tier_mid():
    from app.agents.worldtrip_agent import WorldTripAgent
    agent = WorldTripAgent()
    assert agent._budget_tier(1800) == "средний"


def test_worldtrip_budget_tier_comfort():
    from app.agents.worldtrip_agent import WorldTripAgent
    agent = WorldTripAgent()
    assert agent._budget_tier(3000) == "комфорт"


async def test_worldtrip_collect_cost_data():
    from app.agents.worldtrip_agent import WorldTripAgent
    agent = WorldTripAgent()
    data = await agent._collect_cost_data(1500)
    assert isinstance(data, list)
    assert len(data) >= 1
    # All returned cities must be within budget * 1.2
    for item in data:
        assert item["monthly_usd"] <= 1500 * 1.2


async def test_worldtrip_plan_returns_dict():
    from app.agents.worldtrip_agent import WorldTripAgent

    with patch("app.agents.worldtrip_agent.search_travel_info", AsyncMock(return_value=[])):
        agent = WorldTripAgent()
        result = await agent.plan(budget_usd=1500, duration_months=6)

    assert "budget_usd" in result
    assert result["budget_usd"] == 1500
    assert "plan_text" in result
    assert isinstance(result["plan_text"], str)
