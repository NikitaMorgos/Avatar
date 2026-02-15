#!/bin/bash
# Установка Collect-бота на Ubuntu/Debian VPS для работы 24/7
# Аналог deploy.sh из проекта GLAVA
#
# Первый запуск:
#   git clone https://github.com/NikitaMorgos/Avatar.git /opt/avatar
#   chmod +x /opt/avatar/deploy/deploy.sh
#   sudo /opt/avatar/deploy/deploy.sh

set -e

APP_DIR=/opt/avatar
REPO_URL="${REPO_URL:-https://github.com/NikitaMorgos/Avatar.git}"
SERVICE_USER="${SERVICE_USER:-avatar}"

echo "=== Avatar Collect: установка на VPS ==="

# 1. Системные зависимости
echo "[1/7] Установка системных пакетов..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

# 2. Пользователь avatar (если нет)
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "[2/7] Создание пользователя $SERVICE_USER..."
    sudo adduser --disabled-password --gecos "" "$SERVICE_USER" || true
else
    echo "[2/7] Пользователь $SERVICE_USER уже есть"
fi

# 3. Папка приложения
echo "[3/7] Создание папки..."
sudo mkdir -p "$APP_DIR"
sudo chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# 4. Клонирование/обновление кода
echo "[4/7] Развёртывание кода..."
if [ -d "$APP_DIR/.git" ]; then
    (cd "$APP_DIR" && sudo -u "$SERVICE_USER" git pull)
elif [ -n "$REPO_URL" ] && [[ "$REPO_URL" == http* ]]; then
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$APP_DIR"
else
    echo "Скопируй проект в $APP_DIR вручную:"
    echo "  scp -r ./Avatar root@SERVER_IP:/tmp/avatar && sudo mv /tmp/avatar $APP_DIR"
    echo "  или: git clone https://github.com/NikitaMorgos/Avatar.git $APP_DIR"
    read -p "Нажми Enter после копирования..."
fi

# 5. Виртуальное окружение и зависимости
echo "[5/7] Установка Python-зависимостей..."
sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# 6. .env
echo "[6/7] Настройка .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/config/.env.example" "$APP_DIR/.env"
    sudo chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
    echo "ВАЖНО: отредактируй $APP_DIR/.env и заполни BOT_TOKEN, CHANNEL_ID (опц.)"
    echo "  nano $APP_DIR/.env"
else
    echo ".env уже существует"
fi

# 7. systemd
echo "[7/7] Установка systemd-сервиса..."
sudo cp "$APP_DIR/deploy/collect-bot.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable collect-bot

echo ""
echo "=== Готово ==="
echo "Дальше:"
echo "  1. nano $APP_DIR/.env   # укажи BOT_TOKEN"
echo "  2. sudo systemctl start collect-bot"
echo "  3. sudo systemctl status collect-bot"
echo "  4. sudo journalctl -u collect-bot -f   # логи"
echo ""
echo "Если была ошибка Conflict — сначала: cd $APP_DIR && ./venv/bin/python deploy/fix_webhook.py"
