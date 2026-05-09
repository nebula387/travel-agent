#!/usr/bin/env bash
# =============================================================================
# deploy/setup.sh — одноразовая настройка Ubuntu 24.04 GCE VM
# Запускать с правами root: sudo bash deploy/setup.sh
# Идемпотентен: пропускает уже установленные компоненты
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
step() { echo -e "\n${GREEN}===== $* =====${NC}"; }

[[ $EUID -ne 0 ]] && { echo "Запускай с sudo или как root"; exit 1; }

APP_DIR="/opt/travel-agent"
APP_USER="deploy"

# ── 1. System packages ────────────────────────────────────────────────────────
step "1. Системные пакеты"
apt-get update -qq
apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg lsb-release \
    ufw fail2ban git unzip python3 python3-pip
ok "Базовые пакеты установлены"

# ── 2. Docker ─────────────────────────────────────────────────────────────────
step "2. Docker"
if command -v docker &>/dev/null; then
    ok "Docker уже установлен ($(docker --version | cut -d' ' -f3 | tr -d ','))"
else
    warn "Устанавливаю Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
    ok "Docker установлен"
fi

# ── 3. Docker Compose v2 ──────────────────────────────────────────────────────
step "3. Docker Compose v2"
if docker compose version &>/dev/null; then
    ok "Docker Compose v2 уже есть ($(docker compose version --short))"
elif command -v docker-compose &>/dev/null; then
    ok "docker-compose standalone уже есть ($(docker-compose --version | cut -d' ' -f3 | tr -d ','))"
else
    warn "Устанавливаю Docker Compose v2 standalone..."
    COMPOSE_VER="2.29.1"
    curl -SL "https://github.com/docker/compose/releases/download/v${COMPOSE_VER}/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ok "docker-compose ${COMPOSE_VER} установлен"
fi

# ── 4. Certbot ────────────────────────────────────────────────────────────────
step "4. Certbot"
if command -v certbot &>/dev/null; then
    ok "Certbot уже установлен ($(certbot --version 2>&1))"
else
    warn "Устанавливаю certbot..."
    apt-get install -y certbot python3-certbot-nginx
    ok "Certbot установлен"
fi

# ── 5. UFW firewall ───────────────────────────────────────────────────────────
step "5. UFW Firewall"
if ufw status | grep -q "Status: active"; then
    ok "UFW уже активен"
    ufw status numbered
else
    warn "Настраиваю UFW..."
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow http
    ufw allow https
    # GCE healthcheck проходит через метаданные, но на всякий случай
    ufw --force enable
    ok "UFW настроен"
fi

# Убедиться что 8001 закрыт снаружи (только через nginx)
if ufw status | grep -q "8001"; then
    warn "Порт 8001 открыт в UFW — закрываю (он должен быть только через nginx)"
    ufw delete allow 8001 2>/dev/null || true
fi

# ── 6. Deploy user ────────────────────────────────────────────────────────────
step "6. Пользователь для деплоя"
if id "$APP_USER" &>/dev/null; then
    ok "Пользователь '$APP_USER' уже существует"
else
    useradd -m -s /bin/bash "$APP_USER"
    ok "Пользователь '$APP_USER' создан"
fi
usermod -aG docker "$APP_USER" 2>/dev/null && ok "$APP_USER добавлен в группу docker" || true

# ── 7. App directory ──────────────────────────────────────────────────────────
step "7. Директория приложения"
if [[ -d "$APP_DIR/.git" ]]; then
    ok "Репозиторий уже клонирован в $APP_DIR"
else
    warn "Директория $APP_DIR не является git-репозиторием."
    warn "Если проект уже там — убедись что git init/clone выполнен."
    mkdir -p "$APP_DIR"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
fi

# ── 8. Nginx ──────────────────────────────────────────────────────────────────
step "8. Nginx"
if command -v nginx &>/dev/null; then
    ok "Nginx уже установлен ($(nginx -v 2>&1))"
else
    apt-get install -y nginx
    systemctl enable --now nginx
    ok "Nginx установлен"
fi

# ── Итог ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}  Настройка завершена!${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo ""
echo "Следующие шаги:"
echo ""
echo "  1. Убедись что .env создан:"
echo "     sudo -u $APP_USER cp $APP_DIR/.env.example $APP_DIR/.env"
echo "     sudo -u $APP_USER nano $APP_DIR/.env"
echo ""
echo "  2. Получи SSL-сертификат (первый раз):"
echo "     # Сначала установи временный nginx конфиг для ACME:"
echo "     sudo cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/bot.grip2peak.com"
echo "     sudo ln -sf /etc/nginx/sites-available/bot.grip2peak.com /etc/nginx/sites-enabled/"
echo "     # Временно убери SSL блок или используй --standalone:"
echo "     sudo certbot --nginx -d bot.grip2peak.com --non-interactive --agree-tos -m your@email.com"
echo ""
echo "  3. Запусти деплой:"
echo "     cd $APP_DIR && sudo -u $APP_USER bash deploy/deploy.sh"
echo ""
echo "  4. Зарегистрируй Telegram webhook:"
echo "     cd $APP_DIR && bash deploy/set_webhook.sh"
