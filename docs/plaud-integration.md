# Интеграция Plaud → Raw (Avatar)

Голосовые заметки из Plaud попадают в Raw через Zapier и webhook.

---

## Что нужно

1. **Plaud** — приложение/устройство (у тебя уже есть)
2. **Zapier** — бесплатный аккаунт
3. **Avatar API** — запущен на VPS (collect_api с webhook)
4. **Публичный HTTPS** — URL для webhook (VPS + nginx или ngrok для теста)

---

## Шаг 1. Запусти API на VPS

```bash
# API уже в проекте
sudo systemctl start collect-api
# Или: python -m api.collect_api
```

API слушает порт 8080. Нужен публичный URL, например:
- `https://avatar.example.com` (nginx + Let's Encrypt)
- Или `https://ТВОЙ_IP:8080` (если порт открыт и есть HTTPS)

Для локального теста: [ngrok](https://ngrok.com) — `ngrok http 8080` даст временный HTTPS URL.

---

## Шаг 2. Укажи RAW_OWNER_USER_ID

В `.env` на VPS добавь твой Telegram user_id (для привязки Raw-записей к тебе):

```env
RAW_OWNER_USER_ID=577528
```

Узнать user_id: напиши боту [@userinfobot](https://t.me/userinfobot) в Telegram.

---

## Шаг 3. Подключи Plaud к Zapier

1. В Plaud: **Explore** → **Integrations** → **Zapier**
2. Войди в Zapier (email или Google)
3. Нажми **Allow access** в Plaud

---

## Шаг 4. Создай Zap

1. **Trigger:** Plaud → **Transcript & Summary Ready**
   - Подключи аккаунт Plaud, если ещё не подключён
   - Настрой триггер (минимальная длина записи и т.п.)
   - Нажми **Test trigger** — выбери тестовую запись

2. **Action:** Webhooks by Zapier → **POST**
   - **URL:** `https://ТВОЙ_ДОМЕН/api/plaud/webhook`
   - **Payload Type:** JSON
   - **Data:** добавь поля из Plaud:
     - `transcript` ← Transcript (из шага 1)
     - `summary` ← Summary (из шага 1)
     - `title` ← Title (если есть)

   Или один общий блок: **Include raw data from previous step** — Zapier отправит весь объект.

3. Сохрани и включи Zap.

---

## Шаг 5. Проверка

Сделай новую голосовую заметку в Plaud. После транскрипции Zap запустится, отправит данные на webhook, и запись появится в Raw с `source='Plaud'`.

Проверить Raw в БД:
```bash
sqlite3 db/collect.db "SELECT id, title, source, created_at FROM raw WHERE source='Plaud' ORDER BY id DESC LIMIT 5;"
```

---

## Дальше: AI-обработка

После сохранения в Raw можно добавить пайплайн:
- Суммаризация
- Классификация (GTD Type)
- Предложение тегов/проектов

См. `docs/raw-inbox-spec.md`, шаг 1.4.
