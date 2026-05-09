import asyncio
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.currency import get_cost_of_living
from app.tools.search import search_travel_info

logger = logging.getLogger(__name__)

# Default itinerary regions for budget nomads with RU passport
_DEFAULT_REGIONS = [
    ("Юго-Восточная Азия", ["Таиланд", "Вьетнам", "Индонезия", "Камбоджа"]),
    ("Европа", ["Грузия", "Армения", "Сербия", "Черногория"]),
    ("Латинская Америка", ["Колумбия", "Мексика", "Аргентина"]),
]

_BUDGET_TIERS = {
    "бюджетный": (700, 1200),
    "средний": (1200, 2500),
    "комфорт": (2500, 5000),
}


class WorldTripAgent(BaseAgent):

    async def run(self, query: str, ctx) -> dict[str, Any]:
        try:
            budget = await ctx.read("monthly_budget", 1500)
            passport = await ctx.read("passport_country", "Россия")
            plan = await self.plan(
                budget_usd=budget,
                duration_months=6,
                interests=query,
                passport=passport,
            )
            return {"worldtrip": plan}
        except Exception:
            logger.exception("WorldTripAgent failed")
            return {"error": "worldtrip_agent_error"}

    async def plan(
        self,
        budget_usd: int,
        duration_months: int,
        interests: str = "",
        passport: str = "Россия",
    ) -> dict[str, Any]:
        """
        Строит маршрут кругосветки по бюджету.
        Возвращает структурированный план с ценами и визами.
        """
        # Parallel: gather CoL data + search current visa/nomad info
        col_task = self._collect_cost_data(budget_usd)
        search_task = self._search_nomad_info(interests, passport)
        col_data, search_results = await asyncio.gather(col_task, search_task)

        # Generate full plan via Gemini
        plan_text = await self._generate_plan(
            budget_usd, duration_months, interests, passport, col_data, search_results
        )

        return {
            "budget_usd": budget_usd,
            "duration_months": duration_months,
            "passport": passport,
            "interests": interests,
            "plan_text": plan_text,
            "cost_data": col_data,
            "search_sources": search_results[:3],
        }

    async def _collect_cost_data(self, budget_usd: int) -> list[dict]:
        """Собрать стоимость жизни для топ-городов по бюджету."""
        top_cities = [
            "Бангкок", "Чиангмай", "Хошимин", "Бали", "Тбилиси",
            "Ереван", "Белград", "Котор", "Медельин", "Мехико",
        ]
        results = []
        for city in top_cities:
            col = get_cost_of_living(city)
            if col:
                monthly = col.get("total_budget", 9999)
                if monthly <= budget_usd * 1.2:  # include cities within 20% of budget
                    results.append({
                        "city": city,
                        "monthly_usd": monthly,
                        "feasible": monthly <= budget_usd,
                    })
        return sorted(results, key=lambda x: x["monthly_usd"])

    async def _search_nomad_info(self, interests: str, passport: str) -> list[dict]:
        """Поиск актуальной информации для номадов."""
        queries = [
            f"лучшие страны для цифровых номадов 2025 {passport} паспорт",
            f"безвизовые страны {passport} паспорт 2025 список",
        ]
        if interests:
            queries.append(f"путешествие {interests} бюджет 2025")

        results_combined: list[dict] = []
        for q in queries[:2]:  # limit to 2 searches to save time
            found = await search_travel_info(q, max_results=3)
            results_combined.extend(found)
        return results_combined[:6]

    async def _generate_plan(
        self,
        budget: int,
        months: int,
        interests: str,
        passport: str,
        col_data: list[dict],
        search_results: list[dict],
    ) -> str:
        # Build cities summary
        affordable = [c for c in col_data if c["feasible"]]
        cities_str = ", ".join(
            f"{c['city']} (${c['monthly_usd']}/мес)" for c in affordable[:8]
        )

        # Build search snippets
        snippets = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')[:120]}"
            for r in search_results[:4]
        )

        tier = self._budget_tier(budget)

        prompt = (
            f"Составь план кругосветного путешествия для номада с {passport} паспортом.\n\n"
            f"Параметры:\n"
            f"- Бюджет: ${budget}/мес ({tier})\n"
            f"- Длительность: {months} месяцев\n"
            f"- Интересы: {interests or 'пляж, культура, еда, коворкинг'}\n\n"
            f"Доступные города по бюджету: {cities_str or 'данные не загружены'}\n\n"
            f"Актуальная информация:\n{snippets or 'нет данных'}\n\n"
            "Составь конкретный маршрут:\n"
            "1. Список стран/городов с указанием сколько месяцев проводить\n"
            "2. Примерный бюджет на каждую локацию\n"
            "3. Визовые нюансы для RU паспорта\n"
            "4. Лучший порядок посещения (с учётом климата и виз)\n"
            "5. 3 лайфхака для экономии на этом маршруте\n\n"
            "Формат: текст для Telegram, эмодзи 🌍, конкретные цифры. Около 300-400 слов."
        )
        return await self._llm(prompt)

    def _budget_tier(self, budget: int) -> str:
        for name, (low, high) in _BUDGET_TIERS.items():
            if low <= budget < high:
                return name
        return "комфорт" if budget >= 2500 else "мега-бюджетный"
