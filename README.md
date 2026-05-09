# 🌍 Travel Agent — AI-Powered Telegram Travel Planner

> Budget travel planning via Telegram, powered by Google Gemini AI and a multi-agent system.

A personal project for digital nomads: visa requirements, cheap flights, cost of living,
weather forecasts, and round-the-world trip planning — all from a single Telegram chat.

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green?logo=fastapi)](https://fastapi.tiangolo.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram)](https://core.telegram.org/bots)
[![Gemini](https://img.shields.io/badge/Gemini-1.5_Flash-orange?logo=google)](https://aistudio.google.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)](https://docker.com)

---

## What it does

Send a message to the bot — it figures out what you need and queries multiple data sources in parallel:

| Command | What you get |
|---------|-------------|
| `/explore Bangkok` | Cost of living, best nomad neighborhoods, map |
| `/visa Vietnam` | Visa requirements for your passport, current rules |
| `/weather Bali` | 7-day forecast + best season to visit |
| `/flights Moscow Bangkok` | Cheapest cached prices + Aviasales deeplink |
| `/budget Chiang Mai` | Monthly breakdown: rent, food, coworking, transport |
| `/worldtrip` | Full 6-month round-the-world plan within your budget |
| `/nomad` | Top cities matching your budget right now |

---

## Architecture

```
Telegram  ──▶  FastAPI webhook  ──▶  Orchestrator
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    ▼         ▼           ▼           ▼          ▼
               VisaAgent  WeatherAgent  FlightAgent  BudgetAgent MapsAgent
                    │         │           │           │          │
               DuckDuckGo  WeatherAPI  Travelpayouts  Static DB  Google Maps
               (no API key) + OWM       deeplinks    50+ cities
                    │
                    └──▶  Gemini 1.5 Flash  ──▶  Russian-language response
                          (Groq fallback)

SharedContext: Redis (fast, 1h TTL) + PostgreSQL (persistent)
Celery Beat:   price monitoring every 6h, cache cleanup every 1h
```

The orchestrator classifies intent via keyword matching (fast path) or Gemini disambiguation,
then runs relevant agents with `asyncio.gather()` in parallel, and synthesizes results into
a single coherent Telegram message.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11, async/await throughout |
| Web Framework | FastAPI + Uvicorn |
| Telegram | python-telegram-bot v21 (webhook mode) |
| Primary LLM | Google Gemini 1.5 Flash |
| Fallback LLM | Groq Llama 3.1 70B |
| Task Queue | Celery + Redis |
| Database | PostgreSQL 16 + SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| HTTP Client | httpx (async, 10s timeout) |
| Search | DuckDuckGo Lite (HTML scraping, no API key needed) |
| Maps | Google Maps API (geocoding, places, directions) |
| Weather | WeatherAPI.com → OpenWeatherMap fallback |
| Flights | Travelpayouts Data API + Aviasales deeplinks |
| Currency | ExchangeRate-API (Redis cached 1h) |
| Containers | Docker + Docker Compose |
| Hosting | Google Compute Engine (Ubuntu 24.04) |
| CI/CD | GitHub Actions → SSH deploy |
| Reverse Proxy | Nginx + Let's Encrypt SSL |

---

## Key Design Decisions

**Parallel agent execution** — `asyncio.gather()` runs all relevant agents simultaneously.
A query like "weather and budget for Bali" fires WeatherAgent + BudgetAgent in parallel,
halving response time.

**Dual-persistence context** — `SharedContext` writes to Redis immediately (fast reads, 1h TTL)
and to PostgreSQL asynchronously (survives restarts). Agents share state across a session.

**LLM for synthesis, tools for data** — Agents fetch structured data from APIs/static DBs,
then Gemini synthesizes it into conversational Russian. No hallucinated prices or visa rules.

**No-downtime deploy** — `docker compose up --no-deps app worker` restarts only app containers;
PostgreSQL and Redis stay up. Alembic runs migrations after the new container is healthy.

**Cost-free search** — DuckDuckGo Lite HTML scraping via BeautifulSoup4 gives current visa
and travel info without an API key or subscription.

---

## Local Development

```bash
# Clone and configure
git clone https://github.com/yourusername/travel-agent.git
cd travel-agent
cp .env.example .env
# Fill in at minimum: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY

# Start all services
docker compose up -d

# Apply DB migrations
docker compose exec app alembic upgrade head

# Watch logs
docker compose logs -f app

# Run tests
docker compose exec app pytest tests/ -v
```

Minimum required API keys for basic functionality:
- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
- `GEMINI_API_KEY` — free at [aistudio.google.com](https://aistudio.google.com)

All other keys are optional (features degrade gracefully with fallbacks).

---

## Project Structure

```
travel-agent/
├── app/
│   ├── agents/
│   │   ├── base.py          # BaseAgent with Gemini + Groq fallback
│   │   ├── orchestrator.py  # Intent classification + parallel dispatch + synthesis
│   │   ├── visa_agent.py    # Web search + Gemini visa analysis
│   │   ├── weather_agent.py # WeatherAPI + OWM + Gemini travel advice
│   │   ├── flight_agent.py  # Travelpayouts prices + Aviasales deeplinks
│   │   ├── budget_agent.py  # 50-city CoL database + currency conversion
│   │   ├── maps_agent.py    # Google Maps geocoding + places + routes
│   │   └── worldtrip_agent.py  # Full round-the-world planner via Gemini
│   ├── bot/
│   │   ├── handlers.py      # ConversationHandler + 10 commands + callbacks
│   │   ├── keyboards.py     # InlineKeyboardMarkup builders
│   │   └── messages.py      # All user-facing text templates
│   ├── tools/               # Raw API integrations (maps, weather, flights, currency, search)
│   ├── models/              # SQLAlchemy async models (User, Trip, AgentContext, SearchCache)
│   └── memory/
│       └── context.py       # SharedContext: Redis + PostgreSQL dual persistence
├── workers/
│   ├── celery_app.py        # Celery config + Beat schedule
│   └── tasks.py             # process_travel_request, monitor_prices, send_notification
├── alembic/                 # Database migrations
├── tests/                   # 44 tests (tools, agents, bot endpoints)
└── deploy/                  # Server setup, nginx config, deploy script
```

---

## Testing

```bash
docker compose exec app pytest tests/ -v
```

```
tests/test_tools.py   — 15 tests: pure functions + httpx mocks (WeatherAPI, DuckDuckGo)
tests/test_agents.py  — 22 tests: intent classification, all 6 agents, orchestrator
tests/test_bot.py     —  6 tests: FastAPI endpoints, webhook routing
─────────────────────────────────────────────────
44 passed in ~5 seconds
```

Tests run without any real external services — Redis and LLM are mocked via `AsyncMock`,
HTTP APIs via `pytest-httpx`.

---

## Deployment

See [DEPLOY.md](DEPLOY.md) for the complete guide. Short version:

```bash
# On VM (first time)
sudo bash deploy/setup.sh
sudo certbot --nginx -d bot.grip2peak.com --agree-tos -m you@email.com

# Every deploy (or automatic via GitHub Actions on push to main)
bash deploy/deploy.sh

# Register Telegram webhook
bash deploy/set_webhook.sh
```

---

## Roadmap

- [ ] `/route` — multi-city itinerary with real transport connections
- [ ] Price alerts — Celery Beat already monitors; need UI to subscribe
- [ ] Accommodation search — Hostelworld / Booking.com scraping
- [ ] OpenSky live flight tracking — show real-time plane positions
- [ ] Web dashboard — trip history, saved routes, budget tracker

---

## License

MIT — feel free to fork and adapt for your own travel bot.
