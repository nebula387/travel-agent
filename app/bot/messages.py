from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User

# ── Onboarding ────────────────────────────────────────────────────────────────

MSG_WELCOME_NEW = (
    "🌍 <b>TRAVEL AGENT</b>\n"
    "<i>Система инициализирована. Добро пожаловать, путник.</i>\n\n"
    "Я помогу спланировать твои приключения:\n"
    "✈️ Авиабилеты и маршруты\n"
    "📋 Визы и документы\n"
    "🌤 Погода и сезонность\n"
    "💰 Стоимость жизни\n"
    "🌍 Кругосветные маршруты\n\n"
    "━━━━━━━━━━━━━━━\n\n"
    "<b>Шаг 1 из 3 — Профиль авантюриста</b>\n\n"
    "🛂 <b>Страна твоего паспорта?</b>\n"
    "<i>Пример: Россия, Беларусь, Казахстан</i>"
)

MSG_ASK_BUDGET = (
    "💰 <b>Шаг 2 из 3 — Бюджет</b>\n\n"
    "Сколько USD в месяц готов тратить?\n"
    "<i>Введи только число. Пример: <code>800</code></i>\n\n"
    "Ориентир:\n"
    "▸ <b>$400–700</b> — ЮВА (Таиланд, Вьетнам, Бали)\n"
    "▸ <b>$700–1200</b> — Европа, Лат. Америка\n"
    "▸ <b>$1200+</b> — Япония, Сингапур, Западная Европа"
)

MSG_ASK_STYLE = (
    "🎒 <b>Шаг 3 из 3 — Стиль путешествий</b>\n\n"
    "Выбери свой стиль — я подберу рекомендации:"
)

MSG_ONBOARD_CANCEL = (
    "⛔ Настройка отменена. Введи /start чтобы начать заново."
)

MSG_BAD_PASSPORT = "❌ Укажи страну. Например: <b>Россия</b>"
MSG_BAD_BUDGET = "❌ Введи только число от 100 до 50000. Например: <b>800</b>"

MSG_THINKING = "🔍 Исследую <b>{subject}</b>…"
MSG_ERROR = "❌ Что-то пошло не так. Попробуй ещё раз через несколько секунд."
MSG_NO_ARGS = "❓ Укажи {what}. Пример: <code>{example}</code>"

# ── Formatters ────────────────────────────────────────────────────────────────

def fmt_onboard_done(passport: str, budget: int, style: str) -> str:
    return (
        "✅ <b>Профиль авантюриста сохранён!</b>\n\n"
        f"🛂 Паспорт: <b>{passport}</b>\n"
        f"💰 Бюджет: <b>${budget}/мес</b>\n"
        f"🎒 Стиль: <b>{style}</b>\n\n"
        "Теперь я подбираю рекомендации под твой профиль.\n\n"
        "<b>Начни исследование:</b>\n"
        "/explore <i>страна</i> — карточка направления\n"
        "/visa <i>страна</i> — визовые требования\n"
        f"/worldtrip {budget} — план кругосветки\n"
        "/help — все команды"
    )


def fmt_welcome_back(user: "User") -> str:
    style = user.travel_style or "не указан"
    budget = f"${user.monthly_budget}/мес" if user.monthly_budget else "не указан"
    passport = user.passport_country or "не указан"
    name = user.first_name or "путник"
    return (
        f"🌍 <b>С возвращением, {name}!</b>\n\n"
        "<b>Твой профиль:</b>\n"
        f"🛂 Паспорт: {passport}\n"
        f"💰 Бюджет: {budget}\n"
        f"🎒 Стиль: {style}\n\n"
        "Куда летим? Выбери действие или напиши запрос:"
    )


def fmt_help() -> str:
    return (
        "🗺 <b>КОМАНДЫ TRAVEL AGENT</b>\n\n"
        "/explore <code>страна</code> — полный обзор направления\n"
        "/visa <code>страна</code> — визы для RU паспорта\n"
        "/weather <code>город</code> — погода сейчас + 7 дней\n"
        "/budget <code>город</code> — стоимость жизни\n"
        "/flights <code>откуда куда дата</code> — варианты перелётов\n"
        "/route <code>откуда куда</code> — оптимальный маршрут\n"
        "/nomad <code>город</code> — инфраструктура для номада\n"
        "/worldtrip <code>бюджет</code> — план кругосветки\n"
        "/status — текущие задачи\n"
        "/start — профиль и главное меню\n\n"
        "💡 <i>Или просто напиши куда хочешь поехать — я разберусь.</i>"
    )


def fmt_stub(command: str, subject: str) -> str:
    return (
        f"⚡ <b>{subject.upper()}</b>\n\n"
        "📡 <i>Подключи API ключи в <code>.env</code> для получения живых данных:</i>\n\n"
        "• <code>GEMINI_API_KEY</code> — аналитика и ответы\n"
        "• <code>WEATHERAPI_KEY</code> — погода\n"
        "• <code>GOOGLE_MAPS_API_KEY</code> — карты и геолокация\n"
        "• <code>TRAVELPAYOUTS_TOKEN</code> — авиабилеты\n\n"
        f"После подключения команда <code>/{command}</code> заработает в полную силу."
    )


def fmt_status(tasks: list[dict]) -> str:
    if not tasks:
        return (
            "📊 <b>СТАТУС СИСТЕМЫ</b>\n\n"
            "✅ FastAPI — работает\n"
            "✅ Redis — работает\n"
            "✅ PostgreSQL — работает\n"
            "✅ Celery worker — работает\n\n"
            "Активных задач нет."
        )
    lines = "\n".join(f"▸ {t['name']}: {t['status']}" for t in tasks)
    return f"📊 <b>АКТИВНЫЕ ЗАДАЧИ</b>\n\n{lines}"
