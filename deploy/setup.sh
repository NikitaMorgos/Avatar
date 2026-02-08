#!/bin/bash
# Скрипт настройки Collect бота на VPS.
# Запускать из /opt/avatar (после git clone).

set -e
AVATAR_DIR="${AVATAR_DIR:-/opt/avatar}"
SERVICE_USER="${SERVICE_USER:-avatar}"

echo ">>> Avatar deploy: $AVATAR_DIR"

# venv
cd "$AVATAR_DIR"
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -q

# .env
if [ ! -f .env ]; then
    cp config/.env.example .env
    echo ">>> Создан .env — отредактируй его: nano $AVATAR_DIR/.env"
else
    echo ">>> .env уже есть"
fi

# systemd
sed "s|/opt/avatar|$AVATAR_DIR|g; s|User=avatar|User=$SERVICE_USER|g; s|Group=avatar|Group=$SERVICE_USER|g" deploy/collect-bot.service | sudo tee /etc/systemd/system/collect-bot.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable collect-bot

echo ""
echo ">>> Готово. Дальше:"
echo "   1. nano $AVATAR_DIR/.env   # укажи BOT_TOKEN"
echo "   2. sudo systemctl start collect-bot"
echo "   3. sudo systemctl status collect-bot"
echo "   4. sudo journalctl -u collect-bot -f   # логи"
