import logging
from typing import Any

from app.agents.base import BaseAgent
from app.tools.currency import get_cost_of_living, format_cost_of_living, convert

logger = logging.getLogger(__name__)


class BudgetAgent(BaseAgent):
    async def run(self, query: str, ctx) -> dict[str, Any]:
        try:
            monthly_budget = await ctx.read("monthly_budget", 1500)
            col = get_cost_of_living(query)
            usd_to_rub = await convert(1, "USD", "RUB")

            if not col:
                return {
                    "budget": None,
                    "error": "city_not_found",
                    "query": query,
                    "usd_to_rub": usd_to_rub,
                }

            budget_text = format_cost_of_living(col)
            advice = await self._synthesize(query, col, monthly_budget, usd_to_rub)

            return {
                "budget": col,
                "budget_text": budget_text,
                "budget_advice": advice,
                "usd_to_rub": usd_to_rub,
                "sources": ["static_col_db", "exchangerate-api"],
            }
        except Exception:
            logger.exception("BudgetAgent failed query=%s", query)
            return {"error": "budget_agent_error"}

    async def _synthesize(
        self, city: str, col: dict, user_budget: int, usd_to_rub: float
    ) -> str:
        monthly = col.get("total_budget", 0)
        rent = col.get("accommodation_budget", 0)
        food = col.get("food_budget", 0)
        transport = col.get("transport", 0)

        surplus = user_budget - monthly
        feasible = "по бюджету ✅" if surplus >= 0 else f"превышает бюджет на ${abs(surplus)} ❌"

        prompt = (
            f"Стоимость жизни в {city}:\n"
            f"- Аренда: ${rent}/мес\n"
            f"- Еда: ${food}/мес\n"
            f"- Транспорт: ${transport}/мес\n"
            f"- Итого: ${monthly}/мес ({monthly * usd_to_rub:.0f} ₽)\n"
            f"- Бюджет пользователя: ${user_budget}/мес → {feasible}\n\n"
            "Дай 2-3 совета как сэкономить в этом городе. "
            "Упомяни лучшие районы для номадов, дешёвую еду, транспорт. Эмодзи 💰."
        )
        return await self._llm(prompt)

    async def calculate(self, city: str, budget_usd: int) -> dict[str, Any]:
        col = get_cost_of_living(city)
        usd_to_rub = await convert(1, "USD", "RUB")
        if not col:
            return {"error": "city_not_found", "city": city}
        monthly = col.get("total_budget", 0)
        return {
            "city": city,
            "monthly_usd": monthly,
            "monthly_rub": round(monthly * usd_to_rub) if usd_to_rub else 0,
            "feasible": budget_usd >= monthly,
            "surplus_usd": budget_usd - monthly,
            "breakdown": col,
        }

    async def compare_cities(self, cities: list[str], budget_usd: int) -> list[dict[str, Any]]:
        results = []
        usd_to_rub = await convert(1, "USD", "RUB")
        for city in cities:
            col = get_cost_of_living(city)
            if col:
                monthly = col.get("total_budget", 0)
                results.append({
                    "city": city,
                    "monthly_usd": monthly,
                    "monthly_rub": round(monthly * usd_to_rub),
                    "feasible": budget_usd >= monthly,
                })
        return sorted(results, key=lambda x: x["monthly_usd"])
