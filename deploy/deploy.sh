#!/usr/bin/env bash
# =============================================================================
# deploy/deploy.sh — деплой travel-agent на GCE VM
#
# Запускать НА СЕРВЕРЕ в директории /opt/travel-agent:
#   bash deploy/deploy.sh
#
# Или через SSH:
#   ssh user@host "bash /opt/travel-agent/deploy/deploy.sh"
#
# Zero-downtime: db и redis НЕ перезапускаются.
# Если изменился requirements.txt — автоматически пересобирает образ.
# =============================================================================
set -euo pipefail

APP_DIR="/opt/travel-agent"
COMPOSE="docker compose"
HEALTH_URL="https://bot.grip2peak.com/health"
MAX_WAIT=60  # секунд ожидания healthy

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }
step() { echo -e "\n${GREEN}=== $* ===${NC}"; }

cd "$APP_DIR"

# ── 1. Git pull ────────────────────────────────────────────────────────────────
step "1. Git pull"
git fetch --quiet origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [[ "$LOCAL" == "$REMOTE" ]]; then
    warn "Уже на актуальном коммите ($LOCAL), продолжаю..."
fi

# Сохраним текущий хэш requirements.txt для сравнения
REQ_BEFORE=$(git show HEAD:requirements.txt 2>/dev/null | md5sum || echo "none")
git pull --ff-only origin main
REQ_AFTER=$(git show HEAD:requirements.txt 2>/dev/null | md5sum || echo "none")
NEW_COMMIT=$(git rev-parse --short HEAD)
ok "Обновлено до $NEW_COMMIT"

# ── 2. Nginx конфиг (если изменился) ──────────────────────────────────────────
step "2. Nginx конфиг"
NGINX_SITE="/etc/nginx/sites-available/bot.grip2peak.com"
if [[ -f "$NGINX_SITE" ]]; then
    if ! diff -q "$NGINX_SITE" deploy/nginx.conf &>/dev/null; then
        warn "nginx.conf изменился — обновляю..."
        sudo cp deploy/nginx.conf "$NGINX_SITE"
        sudo nginx -t && sudo systemctl reload nginx
        ok "Nginx перезагружен"
    else
        ok "Nginx конфиг актуален"
    fi
else
    warn "Nginx конфиг для bot.grip2peak.com не найден — пропускаю."
    warn "Первый раз запусти: sudo bash deploy/setup.sh"
fi

# ── 3. Пересборка образов (если нужно) ────────────────────────────────────────
step "3. Docker образы"
if [[ "$REQ_BEFORE" != "$REQ_AFTER" ]]; then
    warn "requirements.txt изменился — пересобираю образы..."
    $COMPOSE build --no-cache app worker
    ok "Образы пересобраны"
else
    ok "requirements.txt не изменился — пересборка не нужна"
fi

# ── 4. Убедиться что db и redis запущены ──────────────────────────────────────
step "4. Инфраструктура (db, redis)"
$COMPOSE up -d db redis

# Ждём healthy db
echo -n "Жду PostgreSQL..."
for i in $(seq 1 30); do
    if $COMPOSE exec -T db pg_isready -U travel -d travel_agent &>/dev/null; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 1
done

# ── 5. Деплой app и worker (без даунтайма db/redis) ───────────────────────────
step "5. Деплой app + worker + beat"
$COMPOSE up -d --no-deps --remove-orphans app worker beat
ok "Контейнеры запущены"

# ── 6. Alembic миграции ────────────────────────────────────────────────────────
step "6. Миграции БД"
sleep 5  # Дать app время стартовать
$COMPOSE exec -T app alembic upgrade head
ok "Миграции применены"

# ── 7. Healthcheck ────────────────────────────────────────────────────────────
step "7. Healthcheck"
echo -n "Жду ответа от $HEALTH_URL"
WAITED=0
until curl -sf "$HEALTH_URL" &>/dev/null; do
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        echo ""
        fail "Таймаут $MAX_WAIT сек — бот не отвечает на /health"
    fi
    echo -n "."
    sleep 2
    WAITED=$((WAITED + 2))
done
echo ""

HEALTH=$(curl -sf "$HEALTH_URL")
ok "Бот отвечает: $HEALTH"

# ── Итог ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Деплой успешен! Коммит: $NEW_COMMIT${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo "Логи: docker compose logs -f app"
echo "Webhook: bash deploy/set_webhook.sh"
