# Деплой Travel Agent на Google Compute Engine

Сервер: Ubuntu 24.04 GCE VM  
Домен бота: `bot.grip2peak.com` → порт 8001  
Существующий сайт: `grip2peak.com` → не трогаем  
Путь на сервере: `/opt/travel-agent`

---

## Быстрый старт (если сервер уже настроен)

```bash
ssh user@bot.grip2peak.com
cd /opt/travel-agent
bash deploy/deploy.sh
```

---

## Первоначальная настройка сервера

### 1. Системные зависимости

```bash
# На VM
sudo bash deploy/setup.sh
```

Скрипт идемпотентен — проверяет что установлено, доустанавливает только недостающее:
- Docker + Docker Compose v2
- Certbot (SSL)
- UFW (firewall: открыты только 22/80/443)
- Пользователь `deploy` с доступом к docker

### 2. Склонировать проект (если ещё не сделано)

```bash
sudo git clone https://github.com/YOUR_USER/travel-agent.git /opt/travel-agent
sudo chown -R deploy:deploy /opt/travel-agent
```

Или если файлы уже на сервере через rsync:

```bash
cd /opt/travel-agent
git init && git remote add origin https://github.com/YOUR_USER/travel-agent.git
```

### 3. Создать `.env` на сервере

```bash
cd /opt/travel-agent
cp .env.example .env
nano .env
```

Обязательные переменные:

```bash
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...    # от @BotFather
WEBHOOK_URL=https://bot.grip2peak.com       # твой домен
SECRET_KEY=                                 # python3 -c "import secrets; print(secrets.token_hex(20))"
GEMINI_API_KEY=                             # aistudio.google.com
GOOGLE_MAPS_API_KEY=                        # console.cloud.google.com
WEATHERAPI_KEY=                             # weatherapi.com
TRAVELPAYOUTS_TOKEN=                        # travelpayouts.com

# Не менять (используют docker-compose сеть)
DATABASE_URL=postgresql+asyncpg://travel:travel@db:5432/travel_agent
REDIS_URL=redis://redis:6379/0
ENVIRONMENT=production
PORT=8001
```

### 4. Настроить nginx

```bash
sudo cp /opt/travel-agent/deploy/nginx.conf /etc/nginx/sites-available/bot.grip2peak.com
sudo ln -sf /etc/nginx/sites-available/bot.grip2peak.com \
            /etc/nginx/sites-enabled/bot.grip2peak.com
sudo nginx -t
```

> **Если появится ошибка про SSL сертификат** — закомментируй HTTPS-блок в nginx.conf,
> чтобы nginx стартовал только на HTTP. После получения сертификата раскомментируй.

### 5. Получить SSL-сертификат

```bash
# Nginx должен слушать :80 для ACME challenge
sudo systemctl reload nginx

# Получить сертификат
sudo certbot --nginx -d bot.grip2peak.com \
    --non-interactive --agree-tos \
    -m your@email.com

# Проверить авто-обновление
sudo certbot renew --dry-run
```

Certbot сам добавит SSL в nginx конфиг и настроит cron для авторенью.

### 6. Первый запуск

```bash
cd /opt/travel-agent
bash deploy/deploy.sh
```

### 7. Зарегистрировать Telegram Webhook

```bash
cd /opt/travel-agent
bash deploy/set_webhook.sh
```

Или вручную (замени значения):

```bash
TOKEN="1234567890:ABCdef..."
SECRET="твой_secret_key_из_env"
DOMAIN="bot.grip2peak.com"

curl "https://api.telegram.org/bot${TOKEN}/setWebhook" \
    -d "url=https://${DOMAIN}/webhook/${SECRET}" \
    -d 'allowed_updates=["message","callback_query"]' \
    -d 'drop_pending_updates=true'
```

Проверить что webhook зарегистрирован:

```bash
curl "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -m json.tool
```

Ожидаемый ответ:
```json
{
  "ok": true,
  "result": {
    "url": "https://bot.grip2peak.com/webhook/...",
    "has_custom_certificate": false,
    "pending_update_count": 0
  }
}
```

---

## Обновление (деплой новой версии)

Просто запушь в `main` — GitHub Actions сделает остальное автоматически.

Или вручную на сервере:

```bash
ssh deploy@bot.grip2peak.com "bash /opt/travel-agent/deploy/deploy.sh"
```

Что происходит при деплое:
1. `git pull` — обновляет код
2. Если `requirements.txt` изменился — пересобирает Docker образ
3. Перезапускает только `app`, `worker`, `beat` (db и redis не трогает)
4. Применяет Alembic миграции
5. Проверяет `/health` endpoint

---

## Настройка GitHub Actions

### Создать GitHub Secrets

В репозитории: `Settings → Secrets and variables → Actions → New secret`

| Secret | Значение |
|--------|----------|
| `DEPLOY_HOST` | IP или домен VM (`bot.grip2peak.com`) |
| `DEPLOY_USER` | SSH пользователь (`ubuntu` или `deploy`) |
| `DEPLOY_SSH_PRIVATE_KEY` | Приватный SSH ключ (см. ниже) |
| `DEPLOY_PORT` | SSH порт (обычно `22`, можно не задавать) |

### Создать SSH ключ для деплоя

На локальном компьютере:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/travel_agent_deploy
```

Добавить публичный ключ на VM:
```bash
ssh-copy-id -i ~/.ssh/travel_agent_deploy.pub deploy@bot.grip2peak.com
# или вручную:
cat ~/.ssh/travel_agent_deploy.pub >> ~/.ssh/authorized_keys
```

Добавить приватный ключ в GitHub Secret `DEPLOY_SSH_PRIVATE_KEY`:
```bash
cat ~/.ssh/travel_agent_deploy  # скопируй всё включая BEGIN/END строки
```

### Проверить что Actions работают

```bash
git commit -m "test: trigger deploy" --allow-empty
git push origin main
```

Следить за прогрессом: `GitHub → Actions → Deploy to GCE`

---

## Проверка работы бота

```bash
# Статус контейнеров
docker compose ps

# Health endpoint
curl https://bot.grip2peak.com/health

# Логи в реальном времени
docker compose logs -f app

# Логи worker (Celery задачи)
docker compose logs -f worker

# Логи beat (расписание задач)
docker compose logs -f beat

# Последние 100 строк всех сервисов
docker compose logs --tail=100

# Логи nginx
sudo tail -f /var/log/nginx/travel-bot.access.log
sudo tail -f /var/log/nginx/travel-bot.error.log
```

---

## Диагностика проблем

### Бот не отвечает в Telegram

```bash
# 1. Проверить healthcheck
curl https://bot.grip2peak.com/health

# 2. Проверить webhook статус
curl "https://api.telegram.org/bot${TOKEN}/getWebhookInfo"

# 3. Посмотреть логи приложения
docker compose logs --tail=50 app

# 4. Убедиться что контейнер запущен
docker compose ps app
```

### Контейнер не стартует

```bash
# Проверить .env (все ключи должны быть заполнены)
cat /opt/travel-agent/.env | grep -v "^#" | grep -v "^$"

# Попробовать запустить вручную с выводом
docker compose up app
```

### Проблемы с БД

```bash
# Подключиться к PostgreSQL
docker compose exec db psql -U travel -d travel_agent

# Применить миграции вручную
docker compose exec app alembic upgrade head

# Посмотреть текущую версию
docker compose exec app alembic current
```

### Обновить webhook после смены SECRET_KEY

```bash
cd /opt/travel-agent
bash deploy/set_webhook.sh
```

### Полный сброс (осторожно — удалит данные!)

```bash
docker compose down -v          # удаляет тома с данными!
docker compose up -d
docker compose exec app alembic upgrade head
bash deploy/set_webhook.sh
```

---

## Мониторинг и алерты

### Celery задачи

```bash
# Активные задачи
docker compose exec worker celery -A workers.celery_app inspect active

# Статистика задач
docker compose exec worker celery -A workers.celery_app inspect stats

# Расписание beat
docker compose exec beat celery -A workers.celery_app inspect scheduled
```

### Disk и память

```bash
df -h                           # диск
docker system df                # место под Docker
docker compose stats            # RAM/CPU контейнеров
```

### Очистка Docker (если кончается место)

```bash
docker system prune -f          # удалить остановленные контейнеры и неиспользуемые образы
docker volume prune -f          # ОСТОРОЖНО: удаляет неиспользуемые тома
```

---

## Структура файлов на сервере

```
/opt/travel-agent/              ← корень проекта
├── .env                        ← секреты (не в git)
├── docker-compose.yml
├── app/                        ← код (volume mount → hot reload)
├── workers/                    ← Celery (volume mount)
├── alembic/                    ← миграции (volume mount)
└── deploy/
    ├── setup.sh                ← одноразовая настройка сервера
    ├── deploy.sh               ← деплой (запускать для обновлений)
    ├── set_webhook.sh          ← регистрация Telegram webhook
    └── nginx.conf              ← nginx для bot.grip2peak.com

/etc/nginx/sites-available/bot.grip2peak.com    ← nginx конфиг (символическая ссылка)
/etc/letsencrypt/live/bot.grip2peak.com/        ← SSL сертификаты (certbot)
```

---

## Порты

| Порт | Что | Доступен снаружи |
|------|-----|-----------------|
| 8001 | Travel Agent (FastAPI) | Нет (только через nginx) |
| 8000 | Существующий сайт | Нет (только через nginx) |
| 80   | HTTP (redirect → HTTPS) | Да |
| 443  | HTTPS | Да |
| 5432 | PostgreSQL | Нет (только Docker сеть) |
| 6379 | Redis | Нет (только Docker сеть) |
