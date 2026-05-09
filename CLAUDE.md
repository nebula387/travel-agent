# Travel Agent — Claude Code Instructions

## Роль
Ты строишь **travel-agent** — агентную систему для виртуальных путешествий,
управляемую через Telegram. Система помогает планировать бюджетные поездки:
визы, билеты, жильё, маршруты, стоимость жизни, кругосветка.

---

## Стек (не менять без явного запроса)

| Слой | Технология |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI + Uvicorn |
| Telegram | python-telegram-bot v20 (async) |
| LLM основной | Google Gemini 1.5 Flash (google-generativeai) |
| LLM резервный | Groq Llama 3.1 70B |
| Task queue | Celery + Redis |
| Database | PostgreSQL 16 + SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| Container | Docker + Docker Compose |
| Reverse proxy | Nginx |
| Hosting | Google Compute Engine (Ubuntu 24.04) |
| Config | pydantic-settings + .env |

---

## Структура проекта (строго соблюдать)

```
travel-agent/
├── CLAUDE.md                  # ← этот файл
├── .env                       # секреты (не в git)
├── .env.example               # шаблон
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI entrypoint + webhook
│   ├── config.py              # pydantic-settings
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # маршрутизация + синтез
│   │   ├── visa_agent.py
│   │   ├── flight_agent.py
│   │   ├── maps_agent.py
│   │   ├── budget_agent.py
│   │   ├── weather_agent.py
│   │   └── worldtrip_agent.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── maps.py            # Google Maps API
│   │   ├── weather.py         # WeatherAPI + OWM fallback
│   │   ├── flights.py         # Travelpayouts + deeplinks
│   │   ├── currency.py        # ExchangeRate-API + Redis cache
│   │   └── search.py          # DuckDuckGo search
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── handlers.py        # команды /start /explore /route etc
│   │   ├── keyboards.py       # InlineKeyboardMarkup
│   │   └── messages.py        # шаблоны сообщений
│   ├── memory/
│   │   ├── __init__.py
│   │   └── context.py         # SharedContext (Redis + PostgreSQL)
│   └── models/
│       ├── __init__.py
│       ├── base.py            # Base, engine, session
│       ├── user.py            # User модель
│       ├── trip.py            # Trip модель
│       └── cache.py           # AgentContext, SearchCache
├── workers/
│   └── celery_app.py
├── deploy/
│   ├── nginx.conf
│   ├── setup.sh
│   └── deploy.sh
└── tests/
    ├── conftest.py
    ├── test_tools.py
    ├── test_agents.py
    └── test_bot.py
```

---

## Переменные окружения (все обязательны если не указано иное)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=         # @BotFather
WEBHOOK_URL=                # https://yourdomain.com/webhook

# LLM
GEMINI_API_KEY=             # aistudio.google.com
GROQ_API_KEY=               # console.groq.com (опционально)

# Maps & Geo
GOOGLE_MAPS_API_KEY=        # Google Cloud Console

# Weather
WEATHERAPI_KEY=             # weatherapi.com
OPENWEATHER_API_KEY=        # openweathermap.org (fallback)

# Flights
TRAVELPAYOUTS_TOKEN=        # travelpayouts.com

# Flight tracking (live)
OPENSKY_USER=               # opensky-network.org
OPENSKY_PASS=               # opensky-network.org

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/travel_agent
REDIS_URL=redis://redis:6379/0

# App
SECRET_KEY=                 # случайная строка 32+ символа
ENVIRONMENT=development     # development | production
PORT=8001                   # порт (8001 чтобы не конфликтовать с сайтом)
```

---

## Правила написания кода

### Всегда
- Async/await везде где есть I/O (HTTP запросы, БД, Redis)
- Pydantic модели для всех входных/выходных данных агентов
- try/except с логированием для каждого внешнего API вызова
- Timeout=10s для всех HTTP запросов (httpx AsyncClient)
- Кэшировать в Redis: курсы валют (1ч), погода (30мин), стоимость жизни (24ч)
- Логировать через Python logging, не print()
- Все тексты для пользователя — в messages.py, не inline в handlers

### Никогда
- Не хранить API ключи в коде — только через config.py из .env
- Не использовать requests (sync) — только httpx (async)
- Не запускать sync функции в async контексте без run_in_executor
- Не коммитить .env файл

### Агенты
- Каждый агент — async функция или класс с методом `run()`
- Принимает: параметры задачи + user_context dict
- Возвращает: структурированный dict с полями result, sources, error
- Пишет промежуточные результаты в SharedContext
- Оркестратор запускает агентов через asyncio.gather() (параллельно)

### Telegram бот
- Длинные задачи (>2 сек): сначала отправить "🔍 Исследую...", потом edit_message_text
- После каждого ответа — InlineKeyboardMarkup с 2-4 кнопками следующих шагов
- sendLocation() для координат мест на карте
- Форматирование: MarkdownV2, эмодзи, короткие абзацы
- Хранить user_context в PostgreSQL по user_id

---

## API интеграции

### Google Maps (app/tools/maps.py)
```python
import googlemaps
gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
# Используй: directions, places_nearby, geocode, find_place
# Static Maps URL для картинок в Telegram
```

### Gemini (в агентах)
```python
import google.generativeai as genai
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
response = await model.generate_content_async(prompt)
```

### Weather (app/tools/weather.py)
```python
# Primary: GET https://api.weatherapi.com/v1/forecast.json?key={KEY}&q={city}&days=7
# Fallback: GET https://api.openweathermap.org/data/2.5/weather?q={city}&appid={KEY}
# При ошибке primary → автоматически fallback
```

### Travelpayouts Flights (app/tools/flights.py)
```python
# Кэш цен: GET https://api.travelpayouts.com/aviasales/v3/get_latest_prices
# Headers: {"X-Access-Token": settings.TRAVELPAYOUTS_TOKEN}
# Deeplink: https://www.aviasales.com/search/{ORIGIN}{DD}{MON}{DEST}1
# Fallback: https://www.google.com/travel/flights/search?q=flights+{origin}+to+{dest}
```

### OpenSky (live flight tracking)
```python
# GET https://opensky-network.org/api/states/all?lamin=&lomin=&lamax=&lomax=
# Auth: Basic (OPENSKY_USER:OPENSKY_PASS) → 4000 req/day
# Без auth → 400 req/day
```

---

## Проверки перед каждым коммитом

```bash
# 1. Линтинг
ruff check app/ workers/ tests/

# 2. Типизация  
mypy app/ --ignore-missing-imports

# 3. Тесты
pytest tests/ -v --tb=short

# 4. Docker сборка
docker-compose build --no-cache

# 5. Проверить что .env не попал в git
git status | grep -i ".env$" && echo "СТОП: .env в git!" || echo "OK"
```

---

## Команды для быстрого старта

```bash
# Локальная разработка
cp .env.example .env          # заполнить ключи
docker-compose up -d          # запустить все сервисы
docker-compose logs -f app    # смотреть логи

# Миграции
docker-compose exec app alembic upgrade head

# Тесты
docker-compose exec app pytest tests/ -v

# Деплой (на GCE VM)
bash deploy/deploy.sh
```

---

## Порядок разработки (сессии)

1. **Сессия 1** — структура + Docker + config ← НАЧИНАЕМ ЗДЕСЬ
2. **Сессия 2** — Telegram бот + команды
3. **Сессия 3** — инструменты (Maps, Weather, Flights, Currency, Search)
4. **Сессия 4** — агенты (Orchestrator + все субагенты)
5. **Сессия 5** — БД модели + Celery + тесты
6. **Сессия 6** — деплой на Google Cloud

---

## Контекст проекта

- Некоммерческий личный проект
- Пользователь: русскоязычный, путешествует с RU паспортом
- Стиль путешествий: бюджетный номад, не турист
- Целевые страны: Юго-Восточная Азия, Европа, Латинская Америка
- Ключевая фича: `/worldtrip` — план кругосветки по бюджету
- UX: ощущение RPG-игры в реальном мире через Telegram
- Все ответы пользователю: на русском языке
