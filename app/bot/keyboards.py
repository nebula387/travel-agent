from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🌍 Исследовать", "menu:explore"), _btn("📋 Виза", "menu:visa")],
        [_btn("✈️ Билеты", "menu:flights"), _btn("🌤 Погода", "menu:weather")],
        [_btn("💰 Бюджет", "menu:budget"), _btn("🏠 Номад-инфра", "menu:nomad")],
        [_btn("🌐 Кругосветка", "menu:worldtrip"), _btn("❓ Помощь", "menu:help")],
    ])


def kb_style_select() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("🎒 Бюджетный номад", "style:nomad")],
        [_btn("🏖 Турист (комфорт)", "style:tourist")],
        [_btn("💼 Бизнес-путешественник", "style:business")],
    ])


def kb_after_explore(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("📋 Виза", f"visa:{s}"), _btn("🌤 Погода", f"weather:{s}")],
        [_btn("💰 Стоимость жизни", f"budget:{s}"), _btn("🏠 Для номада", f"nomad:{s}")],
        [_btn("✈️ Найти билеты", f"flights:{s}"), _btn("🗺 Маршрут", f"route:{s}")],
        [_btn("📍 На карте", f"map:{s}"), _btn("🏨 Места поблизости", f"places:{s}")],
    ])


def kb_after_visa(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("✈️ Найти билеты", f"flights:{s}"), _btn("🌍 Обзор страны", f"explore:{s}")],
        [_btn("💰 Стоимость жизни", f"budget:{s}"), _btn("🌤 Погода", f"weather:{s}")],
    ])


def kb_after_weather(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("🌍 Обзор страны", f"explore:{s}"), _btn("💰 Бюджет", f"budget:{s}")],
        [_btn("✈️ Найти билеты", f"flights:{s}"), _btn("📋 Виза", f"visa:{s}")],
    ])


def kb_after_budget(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("🌍 Обзор", f"explore:{s}"), _btn("📋 Виза", f"visa:{s}")],
        [_btn("✈️ Билеты", f"flights:{s}"), _btn("🏠 Номад", f"nomad:{s}")],
    ])


def kb_after_flights(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("📋 Нужна виза?", f"visa:{s}"), _btn("🌍 Explore", f"explore:{s}")],
        [_btn("🌤 Погода там", f"weather:{s}"), _btn("💰 Бюджет", f"budget:{s}")],
    ])


def kb_after_nomad(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("💰 Стоимость жизни", f"budget:{s}"), _btn("✈️ Билеты", f"flights:{s}")],
        [_btn("🌍 Обзор", f"explore:{s}"), _btn("📋 Виза", f"visa:{s}")],
    ])


def kb_after_worldtrip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("✈️ Первый рейс", "menu:flights"), _btn("📋 Визы", "menu:visa")],
        [_btn("💰 Детальный бюджет", "menu:budget"), _btn("🗺 Маршруты", "menu:route")],
    ])


def kb_after_route(subject: str) -> InlineKeyboardMarkup:
    s = subject[:18]
    return InlineKeyboardMarkup([
        [_btn("✈️ Найти билеты", f"flights:{s}"), _btn("📋 Виза", f"visa:{s}")],
        [_btn("🌤 Погода", f"weather:{s}"), _btn("💰 Бюджет", f"budget:{s}")],
    ])


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("❌ Отмена", "cancel")]])
