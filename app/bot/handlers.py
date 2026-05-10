from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import update as sa_update
from telegram import InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.models.base import async_session_factory
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
ONBOARD_PASSPORT, ONBOARD_BUDGET, ONBOARD_STYLE = range(3)

# ── Module-level app reference ─────────────────────────────────────────────────
_application: Application | None = None

SYSTEM_PROMPT = (
    "Ты — Travel Agent, эксперт по бюджетным путешествиям. "
    "Отвечай всегда на русском языке. "
    "Пользователи — русскоязычные номады с RU паспортом. "
    "Используй эмодзи и HTML-форматирование: <b>жирный</b>, <i>курсив</i>. "
    "Разделяй разделы строкой ━━━━━━━━━━━━━━━. "
    "Будь конкретным: указывай цены в USD, сроки в днях."
)

# ── DB helpers ─────────────────────────────────────────────────────────────────

async def _get_or_create_user(tg_user) -> User | None:
    try:
        async with async_session_factory() as session:
            user = await session.get(User, tg_user.id)
            if user is None:
                user = User(
                    id=tg_user.id,
                    username=getattr(tg_user, "username", None),
                    first_name=getattr(tg_user, "first_name", None),
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            return user
    except Exception:
        logger.exception("DB get_or_create_user failed")
        return None


async def _save_user(user_id: int, **kwargs) -> None:
    try:
        async with async_session_factory() as session:
            await session.execute(
                sa_update(User).where(User.id == user_id).values(**kwargs)
            )
            await session.commit()
    except Exception:
        logger.exception("DB save_user failed for user_id=%s", user_id)


# ── LLM helper ─────────────────────────────────────────────────────────────────

async def _llm(
    prompt: str,
    timeout: float = 25.0,
    history: list[dict] | None = None,
) -> str | None:
    recent = (history or [])[-10:]

    # Primary: Gemini
    if settings.gemini_api_key and settings.gemini_api_key != "placeholder":
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(
                "gemini-2.0-flash",
                system_instruction=SYSTEM_PROMPT,
            )
            if recent:
                ctx = "\n".join(
                    f"{'User' if m['role'] == 'user' else 'Bot'}: {m['content'][:300]}"
                    for m in recent
                )
                full_prompt = f"Предыдущий диалог:\n{ctx}\n\n{prompt}"
            else:
                full_prompt = prompt
            resp = await asyncio.wait_for(
                model.generate_content_async(full_prompt),
                timeout=timeout,
            )
            return resp.text
        except asyncio.TimeoutError:
            logger.warning("LLM timeout prompt=%s…", prompt[:60])
        except Exception:
            logger.exception("Gemini error, trying Groq fallback")

    # Fallback: Groq via httpx (groq SDK incompatible with httpx>=0.28)
    if settings.groq_api_key and settings.groq_api_key != "placeholder":
        try:
            import httpx
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages.extend(recent)
            messages.append({"role": "user", "content": prompt})
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": messages,
                        "max_tokens": 1500,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            logger.exception("Groq fallback also failed")

    return None


def _add_to_history(context: ContextTypes.DEFAULT_TYPE, user_msg: str, bot_reply: str) -> None:
    history: list[dict] = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": user_msg})
    history.append({"role": "assistant", "content": bot_reply[:500]})
    context.user_data["history"] = history[-20:]


# ── Safe send/edit helpers ─────────────────────────────────────────────────────

async def _edit(msg, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except TelegramError as e:
        logger.warning("edit_text failed: %s", e)


async def _reply(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> Any:
    try:
        return await update.effective_message.reply_html(text, reply_markup=keyboard)
    except TelegramError as e:
        logger.warning("reply_html failed: %s", e)
        return None


# ── Core logic functions (shared by commands + callbacks) ──────────────────────

async def _do_explore(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_explore
    from app.bot.messages import fmt_stub
    from app.tools.maps import search_places

    budget_ctx = f"\nБюджет пользователя: ${user.monthly_budget}/мес." if user and user.monthly_budget else ""
    prompt = (
        f"Дай подробный обзор направления: {subject}.{budget_ctx}\n"
        f"Структура ответа:\n"
        f"🌍 <b>{subject.upper()} — ОБЗОР</b>\n"
        f"1. Базовые факты (валюта, язык, часовой пояс)\n"
        f"2. Стоимость жизни: жильё/еда/транспорт в USD/мес\n"
        f"3. Визовый режим для россиян (срок безвиза)\n"
        f"4. Лучшие города для digital nomad\n"
        f"5. Интернет и коворкинги\n"
        f"6. Лучший сезон для посещения\n"
        f"7. 3 совета бюджетного путешественника\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("explore", subject)

    # Append clickable places from Google Maps
    places = await search_places("tourist attraction", subject, radius=5000)
    if places:
        links = []
        for p in places[:5]:
            url = f"https://www.google.com/maps/place/?q=place_id:{p['place_id']}"
            rating = f" ⭐{p['rating']}" if p.get("rating") else ""
            links.append(f'• <a href="{url}">{p["name"]}</a>{rating}')
        places_block = "\n\n📍 <b>Достопримечательности на карте:</b>\n" + "\n".join(links)
        if len(text) + len(places_block) <= 4000:
            text += places_block

    return text, kb_after_explore(subject)


async def _do_visa(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_visa
    from app.bot.messages import fmt_stub

    passport = (user.passport_country if user and user.passport_country else "Россия")
    prompt = (
        f"Визовые требования для въезда в {subject} с паспортом: {passport}.\n"
        f"Структура ответа:\n"
        f"📋 <b>{subject.upper()} — ВИЗОВЫЕ ТРЕБОВАНИЯ</b>\n"
        f"🛂 Паспорт: {passport}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Безвизовый въезд: срок, условия\n"
        f"2. Продление / визаран\n"
        f"3. Долгосрочные варианты (если есть): ВНЖ, номад-виза\n"
        f"4. Необходимые документы при въезде\n"
        f"5. Ссылки на официальные источники\n"
        f"6. ⚠️ Актуальные предупреждения\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("visa", subject)
    return text, kb_after_visa(subject)


async def _do_weather(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_weather
    from app.bot.messages import fmt_stub

    prompt = (
        f"Погода и климат в {subject}.\n"
        f"Структура ответа:\n"
        f"🌤 <b>{subject.upper()} — ПОГОДА И КЛИМАТ</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Сейчас: примерная температура, осадки\n"
        f"2. По сезонам: зима/весна/лето/осень\n"
        f"3. Лучший период для посещения\n"
        f"4. Чего ожидать путешественнику\n"
        f"5. Что взять с собой\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("weather", subject)
    return text, kb_after_weather(subject)


async def _do_budget(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_budget
    from app.bot.messages import fmt_stub

    style = user.travel_style if user and user.travel_style else "бюджетный номад"
    prompt = (
        f"Стоимость жизни в {subject} для стиля: {style}.\n"
        f"Структура ответа:\n"
        f"💰 <b>{subject.upper()} — СТОИМОСТЬ ЖИЗНИ</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Все цены в USD:\n"
        f"1. Жильё: хостел / апартаменты / коворкинг-хаус\n"
        f"2. Еда: уличная еда / кафе / супермаркет\n"
        f"3. Транспорт: местный / аренда байка / такси\n"
        f"4. Интернет: SIM-карта, скорость, цена\n"
        f"5. Развлечения и прочее\n"
        f"6. Итого: минимум / комфортно / с запасом (в USD/мес)\n"
        f"7. Лайфхаки экономии\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("budget", subject)
    return text, kb_after_budget(subject)


async def _do_flights(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_flights
    from app.bot.messages import fmt_stub

    prompt = (
        f"Варианты перелётов до {subject}.\n"
        f"Структура ответа:\n"
        f"✈️ <b>ПЕРЕЛЁТ В {subject.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Прямые рейсы из Москвы/Питера (если есть)\n"
        f"2. С пересадками: оптимальные маршруты\n"
        f"3. Примерные цены в USD (эконом, туда-обратно)\n"
        f"4. Лучшие авиакомпании для этого направления\n"
        f"5. Когда дешевле покупать билеты\n"
        f"6. Где искать дешёвые билеты\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("flights", subject)
    return text, kb_after_flights(subject)


async def _do_nomad(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_nomad
    from app.bot.messages import fmt_stub
    from app.tools.maps import search_places

    prompt = (
        f"Инфраструктура для digital nomad в {subject}.\n"
        f"Структура ответа:\n"
        f"🏠 <b>{subject.upper()} — ДЛЯ DIGITAL NOMAD</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Интернет: скорость, стабильность, SIM-карты\n"
        f"2. Коворкинги: топ-3, цены за день/месяц\n"
        f"3. Кафе для работы: районы, заведения\n"
        f"4. Сообщество номадов: чаты, события\n"
        f"5. Жильё для долгосрока: Airbnb vs аренда\n"
        f"6. Банки и крипта: как получать деньги\n"
        f"7. Рейтинг Nomad Score (1-10): обоснование\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("nomad", subject)

    cowork, cafes = await asyncio.gather(
        search_places("coworking space", subject, radius=5000),
        search_places("cafe wifi", subject, radius=3000),
    )
    sections = []
    if cowork:
        links = [
            f'• <a href="https://www.google.com/maps/place/?q=place_id:{p["place_id"]}">{p["name"]}</a>'
            + (f' ⭐{p["rating"]}' if p.get("rating") else "")
            for p in cowork[:3]
        ]
        sections.append("💻 <b>Коворкинги на карте:</b>\n" + "\n".join(links))
    if cafes:
        links = [
            f'• <a href="https://www.google.com/maps/place/?q=place_id:{p["place_id"]}">{p["name"]}</a>'
            + (f' ⭐{p["rating"]}' if p.get("rating") else "")
            for p in cafes[:3]
        ]
        sections.append("☕ <b>Кафе для работы на карте:</b>\n" + "\n".join(links))
    if sections:
        block = "\n\n📍 " + "\n\n📍 ".join(sections)
        if len(text) + len(block) <= 4000:
            text += block

    return text, kb_after_nomad(subject)


async def _do_route(subject: str, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_route
    from app.bot.messages import fmt_stub

    budget_ctx = f" Бюджет: ${user.monthly_budget}/мес." if user and user.monthly_budget else ""
    prompt = (
        f"Оптимальный маршрут: {subject}.{budget_ctx}\n"
        f"Структура ответа:\n"
        f"🗺 <b>МАРШРУТ: {subject.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Оптимальный порядок посещения мест\n"
        f"2. Транспорт между точками (стоимость, время)\n"
        f"3. Рекомендуемое время в каждой точке\n"
        f"4. Где остановиться по пути\n"
        f"5. Общая оценка стоимости маршрута\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("route", subject)
    return text, kb_after_route(subject)


async def _do_worldtrip(budget: int, user: User | None) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.keyboards import kb_after_worldtrip
    from app.bot.messages import fmt_stub

    passport = user.passport_country if user and user.passport_country else "Россия"
    prompt = (
        f"Составь план кругосветного путешествия.\n"
        f"Паспорт: {passport}. Бюджет: ${budget}/мес.\n"
        f"Структура ответа:\n"
        f"🌐 <b>КРУГОСВЕТКА — ПЛАН НА ${budget}/МЕС</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"1. Маршрут: 8-12 стран оптимальной последовательностью\n"
        f"2. Для каждой страны: срок пребывания + причина + виза\n"
        f"3. Транспорт между странами: авиа / наземный\n"
        f"4. Распределение бюджета по регионам\n"
        f"5. Итого: продолжительность / общая стоимость\n"
        f"6. ТОП-3 совета для кругосветки\n"
        f"Используй HTML-теги <b> и <i>."
    )
    text = await _llm(prompt) or fmt_stub("worldtrip", "кругосветка")
    return text, kb_after_worldtrip()


# ── Onboarding handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("history", None)
    user = await _get_or_create_user(update.effective_user)
    if user and user.onboarding_done:
        from app.bot.messages import fmt_welcome_back
        from app.bot.keyboards import kb_main_menu
        await _reply(update, fmt_welcome_back(user), kb_main_menu())
        return ConversationHandler.END
    from app.bot.messages import MSG_WELCOME_NEW
    await update.effective_message.reply_html(
        MSG_WELCOME_NEW,
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_PASSPORT


async def recv_passport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if len(text) < 2 or len(text) > 60 or any(c.isdigit() for c in text):
        from app.bot.messages import MSG_BAD_PASSPORT
        await update.message.reply_html(MSG_BAD_PASSPORT)
        return ONBOARD_PASSPORT

    context.user_data["passport"] = text
    from app.bot.messages import MSG_ASK_BUDGET
    await update.message.reply_html(MSG_ASK_BUDGET)
    return ONBOARD_BUDGET


async def recv_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not raw.isdigit():
        from app.bot.messages import MSG_BAD_BUDGET
        await update.message.reply_html(MSG_BAD_BUDGET)
        return ONBOARD_BUDGET

    budget = int(raw)
    if not (100 <= budget <= 50_000):
        from app.bot.messages import MSG_BAD_BUDGET
        await update.message.reply_html(MSG_BAD_BUDGET)
        return ONBOARD_BUDGET

    context.user_data["budget"] = budget
    from app.bot.messages import MSG_ASK_STYLE
    from app.bot.keyboards import kb_style_select
    await update.message.reply_html(MSG_ASK_STYLE, reply_markup=kb_style_select())
    return ONBOARD_STYLE


async def recv_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    style_map = {
        "style:nomad": "🎒 Бюджетный номад",
        "style:tourist": "🏖 Турист",
        "style:business": "💼 Бизнес",
    }
    style = style_map.get(query.data, "🎒 Бюджетный номад")
    passport = context.user_data.get("passport", "Россия")
    budget = context.user_data.get("budget", 0)

    await _save_user(
        update.effective_user.id,
        passport_country=passport,
        monthly_budget=budget,
        travel_style=style,
        onboarding_done=True,
    )

    from app.bot.messages import fmt_onboard_done
    from app.bot.keyboards import kb_main_menu
    await query.edit_message_text(
        fmt_onboard_done(passport, budget, style),
        parse_mode=ParseMode.HTML,
        reply_markup=kb_main_menu(),
    )
    return ConversationHandler.END


async def cancel_onboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app.bot.messages import MSG_ONBOARD_CANCEL
    await _reply(update, MSG_ONBOARD_CANCEL)
    return ConversationHandler.END


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("history", None)
    await _reply(update, "🗑 История диалога очищена. Начинаем заново!")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.bot.messages import fmt_help
    from app.bot.keyboards import kb_main_menu
    await _reply(update, fmt_help(), kb_main_menu())


async def cmd_explore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи страну. Пример: <code>/explore Таиланд</code>")
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"🔍 Исследую <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_explore(subject, user)
    await _edit(msg, text, kb)
    _add_to_history(context, f"explore {subject}", text)


async def cmd_visa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи страну. Пример: <code>/visa Таиланд</code>")
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"📋 Проверяю визовые требования для <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_visa(subject, user)
    await _edit(msg, text, kb)
    _add_to_history(context, f"visa {subject}", text)


async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи город. Пример: <code>/weather Бангкок</code>")
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"🌤 Загружаю погоду для <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_weather(subject, user)
    await _edit(msg, text, kb)


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи город. Пример: <code>/budget Чиангмай</code>")
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"💰 Считаю стоимость жизни в <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_budget(subject, user)
    await _edit(msg, text, kb)


async def cmd_flights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(
            update,
            "❓ Укажи направление. Пример: <code>/flights Москва Бангкок</code>",
        )
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"✈️ Ищу рейсы <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_flights(subject, user)
    await _edit(msg, text, kb)


async def cmd_route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(
            update,
            "❓ Укажи маршрут. Пример: <code>/route Бангкок Чиангмай Паттайя</code>",
        )
        return
    subject = " → ".join(context.args)
    msg = await _reply(update, f"🗺 Строю маршрут <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_route(subject, user)
    await _edit(msg, text, kb)


async def cmd_nomad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи город. Пример: <code>/nomad Чиангмай</code>")
        return
    subject = " ".join(context.args)
    msg = await _reply(update, f"🏠 Анализирую номад-инфраструктуру <b>{subject}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    user = await _get_or_create_user(update.effective_user)
    text, kb = await _do_nomad(subject, user)
    await _edit(msg, text, kb)


async def cmd_worldtrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _get_or_create_user(update.effective_user)
    raw_budget = (context.args[0] if context.args else None) or (
        str(user.monthly_budget) if user and user.monthly_budget else "800"
    )
    try:
        budget = int(raw_budget.replace("$", "").replace(",", ""))
    except ValueError:
        budget = 800

    msg = await _reply(update, f"🌐 Планирую кругосветку на <b>${budget}/мес</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    text, kb = await _do_worldtrip(budget, user)
    await _edit(msg, text, kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.bot.messages import fmt_status
    await _reply(update, fmt_status([]))


async def cmd_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "❓ Укажи место. Пример: <code>/map Wat Pho Bangkok</code>")
        return
    query = " ".join(context.args)
    msg = await _reply(update, f"🗺 Ищу <b>{query}</b> на карте…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    from app.tools.maps import geocode
    geo = await geocode(query)
    if not geo:
        await _edit(msg, f"❌ Место не найдено: <b>{query}</b>\nПопробуй точнее: <code>/map Chatrium Hotel Bangkok</code>")
        return

    lat, lng = geo["lat"], geo["lng"]
    maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗺 Открыть в Google Maps", url=maps_url)]])
    await _edit(msg, f"📍 <b>{geo['formatted_address']}</b>", kb)
    await context.bot.send_location(
        chat_id=update.effective_chat.id,
        latitude=lat,
        longitude=lng,
    )
    context.user_data["map_msg_id"] = msg.message_id


async def cmd_places(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await _reply(update, "❓ Пример: <code>/places хостел Бангкок</code> или <code>/places кафе Чиангмай</code>")
        return
    ptype = context.args[0]
    city = " ".join(context.args[1:])
    msg = await _reply(update, f"🔍 Ищу <b>{ptype}</b> в <b>{city}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    from app.tools.maps import search_places
    places = await search_places(ptype, city, radius=3000)
    if not places:
        await _edit(msg, f"❌ Ничего не найдено: <b>{ptype}</b> в <b>{city}</b>")
        return

    lines = [f"📍 <b>{ptype.upper()} — {city.upper()}</b>\n"]
    for i, p in enumerate(places[:5], 1):
        rating = f"⭐ {p['rating']}" if p.get("rating") else ""
        lines.append(f"{i}. <b>{p['name']}</b> {rating}")
        if p.get("address"):
            lines.append(f"   {p['address']}")
    await _edit(msg, "\n".join(lines))

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    last_place_msg = None
    for p in places[:3]:
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{p['place_id']}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🗺 {p['name']}", url=maps_url)]])
        await context.bot.send_location(
            chat_id=update.effective_chat.id,
            latitude=p["lat"],
            longitude=p["lng"],
        )
        last_place_msg = await update.effective_message.reply_html(
            f"📍 <b>{p['name']}</b>" + (f" ⭐ {p['rating']}" if p.get("rating") else ""),
            reply_markup=kb,
        )
    if last_place_msg:
        context.user_data["map_msg_id"] = last_place_msg.message_id


# ── Free-text handler ──────────────────────────────────────────────────────────

_PENDING_DISPATCH = {
    "explore": _do_explore,
    "visa": _do_visa,
    "weather": _do_weather,
    "budget": _do_budget,
    "flights": _do_flights,
    "nomad": _do_nomad,
    "route": _do_route,
}


async def msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return

    user = await _get_or_create_user(update.effective_user)
    if user and not user.onboarding_done:
        await update.message.reply_html("Сначала настрой профиль командой /start 👆")
        return

    # Remove keyboard from previous map message
    map_msg_id = context.user_data.pop("map_msg_id", None)
    if map_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=update.effective_chat.id,
                message_id=map_msg_id,
                reply_markup=None,
            )
        except Exception:
            pass

    # If user clicked a menu button — route to the right command
    pending_cmd = context.user_data.pop("pending_cmd", None)
    if pending_cmd and pending_cmd in _PENDING_DISPATCH:
        msg = await _reply(update, f"🔍 Загружаю <b>{text}</b>…")
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        cmd_text, kb = await _PENDING_DISPATCH[pending_cmd](text, user)
        await _edit(msg, cmd_text, kb)
        _add_to_history(context, text, cmd_text)
        return

    history: list[dict] = context.user_data.setdefault("history", [])

    msg = await _reply(update, f"🔍 Исследую <b>{text}</b>…")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    prompt = (
        f"Пользователь написал: «{text}»\n"
        f"Ответь как travel-эксперт. Если это название страны/города — дай краткий обзор. "
        f"Если вопрос о путешествии — ответь по существу. "
        f"Используй HTML-теги <b> и <i> и эмодзи."
    )
    answer = await _llm(prompt, history=history)
    if not answer:
        answer = "🤖 LLM временно недоступен. Попробуй через минуту или используй команды из /help"
    else:
        _add_to_history(context, text, answer)

    from app.bot.keyboards import kb_main_menu
    await _edit(msg, answer, kb_main_menu())


# ── Callback query handler ─────────────────────────────────────────────────────

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    # Menu shortcuts (no subject)
    menu_prompts = {
        "menu:explore": ("🌍", "Введи страну: <code>/explore Таиланд</code>"),
        "menu:visa": ("📋", "Введи страну: <code>/visa Таиланд</code>"),
        "menu:flights": ("✈️", "Введи маршрут: <code>/flights Москва Бангкок</code>"),
        "menu:weather": ("🌤", "Введи город: <code>/weather Бангкок</code>"),
        "menu:budget": ("💰", "Введи город: <code>/budget Бангкок</code>"),
        "menu:nomad": ("🏠", "Введи город: <code>/nomad Бангкок</code>"),
        "menu:worldtrip": ("🌐", "Используй: <code>/worldtrip 800</code>"),
        "menu:route": ("🗺", "Введи маршрут: <code>/route Бангкок Чиангмай</code>"),
        "menu:help": None,
        "cancel": None,
    }

    if data in menu_prompts:
        if data == "menu:help":
            from app.bot.messages import fmt_help
            from app.bot.keyboards import kb_main_menu
            await query.edit_message_text(
                fmt_help(), parse_mode=ParseMode.HTML, reply_markup=kb_main_menu()
            )
        elif data == "cancel":
            context.user_data.pop("pending_cmd", None)
            await query.edit_message_text("❌ Отменено.")
        else:
            emoji, hint = menu_prompts[data]
            cmd_name = data.split(":")[1]
            if cmd_name in _PENDING_DISPATCH:
                context.user_data["pending_cmd"] = cmd_name
            from app.bot.keyboards import kb_cancel
            await query.edit_message_text(
                f"{emoji} {hint}", parse_mode=ParseMode.HTML, reply_markup=kb_cancel()
            )
        return

    # Subject-based callbacks: "cmd:subject"
    if ":" not in data:
        return

    cmd, subject = data.split(":", 1)
    if not subject:
        return

    # Map callback — send location pin without editing the original message
    if cmd == "places":
        await query.answer("🔍 Ищу места…")
        from app.tools.maps import search_places
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        places = await search_places("", subject, radius=3000)
        for p in places[:3]:
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{p['place_id']}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"🗺 {p['name']}", url=maps_url)]])
            await context.bot.send_location(
                chat_id=update.effective_chat.id,
                latitude=p["lat"],
                longitude=p["lng"],
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📍 <b>{p['name']}</b>" + (f" ⭐ {p['rating']}" if p.get("rating") else ""),
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        return

    if cmd == "map":
        await query.answer("🗺 Ищу на карте…")
        from app.tools.maps import geocode
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        geo = await geocode(subject)
        if geo:
            maps_url = f"https://www.google.com/maps/search/?api=1&query={geo['lat']},{geo['lng']}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗺 Google Maps", url=maps_url)]])
            await context.bot.send_location(
                chat_id=update.effective_chat.id,
                latitude=geo["lat"],
                longitude=geo["lng"],
            )
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📍 <b>{geo['formatted_address']}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        return

    await query.edit_message_text(
        f"🔍 Загружаю <b>{subject}</b>…", parse_mode=ParseMode.HTML
    )

    user = await _get_or_create_user(update.effective_user)

    dispatch = {
        "explore": _do_explore,
        "visa": _do_visa,
        "weather": _do_weather,
        "budget": _do_budget,
        "flights": _do_flights,
        "nomad": _do_nomad,
        "route": _do_route,
    }

    handler_fn = dispatch.get(cmd)
    if not handler_fn:
        return

    try:
        text, kb = await handler_fn(subject, user)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except TelegramError as e:
        logger.warning("cb_handler edit failed: %s", e)
    except Exception:
        logger.exception("cb_handler error cmd=%s subject=%s", cmd, subject)
        from app.bot.messages import MSG_ERROR
        await query.edit_message_text(MSG_ERROR, parse_mode=ParseMode.HTML)


# ── Error handler ──────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("PTB error: %s", context.error, exc_info=context.error)


# ── Application lifecycle ──────────────────────────────────────────────────────

def _register_handlers(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            ONBOARD_PASSPORT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_passport)
            ],
            ONBOARD_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_budget)
            ],
            ONBOARD_STYLE: [
                CallbackQueryHandler(recv_style, pattern=r"^style:")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_onboard)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("explore", cmd_explore))
    app.add_handler(CommandHandler("visa", cmd_visa))
    app.add_handler(CommandHandler("weather", cmd_weather))
    app.add_handler(CommandHandler("budget", cmd_budget))
    app.add_handler(CommandHandler("flights", cmd_flights))
    app.add_handler(CommandHandler("route", cmd_route))
    app.add_handler(CommandHandler("nomad", cmd_nomad))
    app.add_handler(CommandHandler("worldtrip", cmd_worldtrip))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("map", cmd_map))
    app.add_handler(CommandHandler("places", cmd_places))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.add_error_handler(error_handler)


async def init_application() -> Application | None:
    global _application
    if _application is not None:
        return _application

    token = settings.telegram_bot_token
    if not token or token == "placeholder":
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return None

    try:
        app = Application.builder().token(token).build()
        _register_handlers(app)
        await app.initialize()
        _application = app
        logger.info("PTB application initialized")
        return _application
    except Exception:
        logger.exception("Failed to initialize PTB application")
        return None


async def shutdown_application() -> None:
    global _application
    if _application:
        try:
            await _application.shutdown()
        except Exception:
            logger.exception("Error during PTB shutdown")
        finally:
            _application = None


def get_application() -> Application:
    if _application is None:
        raise RuntimeError("Bot application not initialized — call init_application() first")
    return _application
