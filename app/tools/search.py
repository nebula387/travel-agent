"""DuckDuckGo HTML search — без API ключа, возвращает топ-5 результатов."""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}


async def web_search(
    query: str,
    max_results: int = 5,
    region: str = "ru-ru",
) -> list[dict[str, Any]]:
    """
    Поиск через DuckDuckGo Lite (без API ключа).
    Возвращает список {title, snippet, url}.
    """
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            r = await client.post(
                DDG_LITE_URL,
                data={"q": query, "kl": region, "s": "0"},
            )
            r.raise_for_status()
            return _parse_lite(r.text, max_results)
    except Exception:
        logger.exception("DuckDuckGo search failed query=%s", query)
        return []


def _parse_lite(html: str, max_results: int) -> list[dict[str, Any]]:
    """Парсинг HTML DuckDuckGo Lite."""
    soup = BeautifulSoup(html, "lxml")
    results: list[dict[str, Any]] = []

    # DDG Lite структура: <tr> с классами result-link и result-snippet чередуются
    rows = soup.find_all("tr")
    i = 0
    while i < len(rows) and len(results) < max_results:
        row = rows[i]
        link_td = row.find("td", class_="result-link") or row.find("a", class_="result-link__title")

        # Ищем ссылку в строке
        a_tag = row.find("a")
        if not a_tag:
            i += 1
            continue

        href = a_tag.get("href", "")
        title = a_tag.get_text(strip=True)

        if not href or not title or href.startswith("javascript"):
            i += 1
            continue

        # Следующая строка — сниппет
        snippet = ""
        if i + 1 < len(rows):
            next_row = rows[i + 1]
            snippet_td = next_row.find("td", class_="result-snippet")
            if snippet_td:
                snippet = snippet_td.get_text(strip=True)
                i += 1  # пропустить строку сниппета

        # Резолвинг redirect URLs DuckDuckGo
        url = _extract_url(href)
        if not url:
            i += 1
            continue

        results.append({
            "title": title,
            "snippet": snippet[:300],
            "url": url,
        })
        i += 1

    return results


def _extract_url(href: str) -> str | None:
    """Извлечь реальный URL из DuckDuckGo redirect."""
    if href.startswith("http"):
        return href
    # DDG Lite использует /lite/r?uddg=<encoded_url>
    m = re.search(r"uddg=([^&]+)", href)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return None


async def search_travel_info(
    topic: str,
    city: str | None = None,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """
    Поиск актуальной туристической информации.
    Добавляет контекст к запросу для лучших результатов.
    """
    query = topic
    if city:
        query = f"{city} {topic} 2024 2025"
    return await web_search(query, max_results=max_results)


def format_search_results(results: list[dict[str, Any]], title: str = "Результаты поиска") -> str:
    """Отформатировать результаты для Telegram (HTML)."""
    if not results:
        return "🔎 Результатов не найдено."

    lines = [f"🔎 <b>{title}</b>", "━━━━━━━━━━━━━━━"]
    for i, r in enumerate(results, 1):
        snippet = f"\n<i>{r['snippet']}</i>" if r.get("snippet") else ""
        lines.append(f"{i}. <a href=\"{r['url']}\">{r['title']}</a>{snippet}")

    return "\n\n".join(lines)
