#!/usr/bin/env bash
# Регистрирует webhook в Telegram. Запускать один раз после деплоя.
set -euo pipefail

# Читаем из .env если не заданы в окружении
if [ -f .env ]; then
    set -a; source .env; set +a
fi

: "${TELEGRAM_BOT_TOKEN:?Нужно задать TELEGRAM_BOT_TOKEN}"
: "${WEBHOOK_URL:?Нужно задать WEBHOOK_URL}"
: "${SECRET_KEY:?Нужно задать SECRET_KEY}"

FULL_URL="${WEBHOOK_URL}/webhook/${SECRET_KEY}"

echo "Регистрирую webhook: $FULL_URL"

curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -d "url=${FULL_URL}" \
    -d "allowed_updates=[\"message\",\"callback_query\"]" \
    -d "drop_pending_updates=true" \
    | python3 -m json.tool

echo ""
echo "Проверяю статус:"
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
    | python3 -m json.tool
