# Деплой Avatar на VPS (24/7)

Пошаговая инструкция: от аренды сервера до работающего бота.

---

## Шаг 1. Аренда VPS

### 1.1 Выбери провайдера

| Провайдер | Цена | Регистрация |
|-----------|------|-------------|
| **Timeweb** | от ~150 ₽/мес | timeweb.com |
| **REG.RU** | от ~150 ₽/мес | reg.ru |
| **DigitalOcean** | от $4/мес | digitalocean.com |
| **Hetzner** | от ~4 €/мес | hetzner.com |

Для примера дальше — **Timeweb** (рубли, карта РФ). Логика у остальных похожа.

### 1.2 Создай VPS на Timeweb

1. Зайди на [timeweb.com](https://timeweb.com) → **Регистрация** (если нет аккаунта).
2. Панель → **Облачные серверы** → **Создать сервер**.
3. Параметры:
   - **ОС:** Ubuntu 22.04 LTS
   - **Тариф:** минимальный (1 vCPU, 1 GB RAM — хватит с запасом)
   - **Регион:** любой (Москва, Амстердам — разницы для бота нет)
4. Укажи **пароль root** (придумай и сохрани) или выбери SSH-ключ, если есть.
5. Нажми **Создать** и подожди 1–2 минуты.
6. В панели появится **IP-адрес** сервера (например `123.45.67.89`). Сохрани его.

### 1.3 На других провайдерах

- **REG.RU:** Хостинг → VPS → Заказать → Ubuntu 22.04, минимальный тариф.
- **DigitalOcean:** Create → Droplets → Ubuntu 22.04, Basic $4/mo.
- **Hetzner:** Create → Server → Ubuntu 22.04, CX11 (~4 €).

Везде после создания будет: **IP**, логин **root**, пароль (или SSH-ключ).

---

## Шаг 2. Подключение по SSH

### С Windows (PowerShell или CMD)

```powershell
ssh root@ТВОЙ_IP
```

Например: `ssh root@123.45.67.89`

При первом подключении спросят «Trust this host?» — введи `yes`, затем пароль root.

### Альтернатива: PuTTY

1. Скачай [PuTTY](https://putty.org).
2. Host: твой IP, Port: 22.
3. Open → введи логин `root` и пароль.

---

## Шаг 3. Базовая настройка сервера

Выполни в SSH по очереди:

```bash
# Обновить систему
apt update && apt upgrade -y

# Создать пользователя avatar (будет запускать бота)
adduser avatar
# Введи пароль и остальное (можно Enter)

# Дать права sudo
usermod -aG sudo avatar

# Переключиться на него
su - avatar
```

Теперь все команды — от пользователя `avatar`. `sudo` запросит пароль при необходимости.

---

## Шаг 4. Установка Python и клонирование проекта

```bash
# Установить Python и git
sudo apt install -y python3 python3-venv python3-pip git

# Создать папку для проекта
sudo mkdir -p /opt/avatar
sudo chown avatar:avatar /opt/avatar
cd /opt/avatar

# Клонировать репозиторий (подставь свой GitHub)
git clone https://github.com/NikitaMorgos/Avatar.git .

# Виртуальное окружение и зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Вариант в одну команду:** после `git clone` можешь запустить `chmod +x deploy/setup.sh && ./deploy/setup.sh` — скрипт сам создаст venv и настроит systemd. Дальше — шаги 5 и 6.

---

## Шаг 5. Настройка .env

```bash
# В корне проекта /opt/avatar
cp config/.env.example .env
nano .env
```

В nano:
- Вставь **BOT_TOKEN** (токен от [@BotFather](https://t.me/BotFather))
- Если есть канал — **CHANNEL_ID** (@username или -100xxxxxxxxxx)
- По желанию: POST_SCHEDULE_TIME=20:00, FALLBACK_TIME=23:00

Сохранение в nano: `Ctrl+O` → Enter → `Ctrl+X`

---

## Шаг 6. Установка systemd-сервиса и запуск

```bash
# Скопировать unit-файл
sudo cp deploy/collect-bot.service /etc/systemd/system/

# Применить изменения
sudo systemctl daemon-reload

# Включить автозапуск при перезагрузке
sudo systemctl enable collect-bot

# Запустить бота
sudo systemctl start collect-bot

# Проверить, что работает
sudo systemctl status collect-bot
```

В статусе должно быть `active (running)`. Если ошибка — смотри логи: `sudo journalctl -u collect-bot -n 50`.

---

## Шаг 7. Проверка

1. Открой бота в Telegram — @CollectMyDay_bot (или твой бот)
2. Отправь `/start` — должен ответить
3. Отправь фото с подписью — должно сохраниться

Готово. Бот работает 24/7, перезапустится при падении и после перезагрузки сервера.

---

## Полезные команды

| Действие | Команда |
|----------|---------|
| Посмотреть логи в реальном времени | `sudo journalctl -u collect-bot -f` |
| Перезапустить бота | `sudo systemctl restart collect-bot` |
| Остановить | `sudo systemctl stop collect-bot` |
| Отключить автозапуск | `sudo systemctl disable collect-bot` |

---

## Добавление второго (и следующих) ботов

Для каждого нового бота:

1. Создай отдельную папку (например `/opt/avatar-bot2`) или отдельный репозиторий.
2. Скопируй `deploy/collect-bot.service` в `deploy/другой-бот.service`.
3. Измени в unit-файле:
   - `Description`
   - `ExecStart` — путь к скрипту нового бота
   - имя файла и сервиса: `sudo systemctl start другой-бот`
4. Создай `.env` с токеном нового бота.

Пример структуры для нескольких ботов:
```
/opt/avatar/          → Collect
/opt/avatar-bot2/     → второй бот
/opt/avatar-bot3/     → третий бот
```

---

## Обновление кода

```bash
cd /opt/avatar
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart collect-bot
```

---

## Бэкап БД

SQLite-файл: `/opt/avatar/db/collect.db`

```bash
# Ручной бэкап
cp /opt/avatar/db/collect.db ~/backup/collect-$(date +%Y%m%d).db

# Или настрой cron для ежедневного бэкапа
crontab -e
# Добавь строку:
0 3 * * * cp /opt/avatar/db/collect.db /home/avatar/backup/collect-$(date +\%Y\%m\%d).db
```

---

## Firewall (опционально)

```bash
sudo ufw allow 22/tcp   # SSH
sudo ufw enable
```

Бот не открывает порты — он сам подключается к Telegram (outbound), так что входящие порты не нужны.
